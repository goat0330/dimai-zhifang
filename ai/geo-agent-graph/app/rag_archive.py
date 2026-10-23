"""Review-gated write-back of an approved report to Yichang's evidence KB."""

import asyncio
from io import BytesIO
from pathlib import Path
import re
import struct
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import httpx

from .config import settings
from .yichang_contract import YICHANG_KNOWLEDGE_BASES


def _java_report_id(report: dict) -> str | None:
    value = report.get("report_id", report.get("reportId"))
    associations = report.get("associations")
    if value in (None, "") and isinstance(associations, dict):
        value = associations.get("new_report_id")
        if value in (None, "", "unknown"):
            existing = associations.get("existing_report_ids")
            value = existing[0] if isinstance(existing, list) and existing else None
    return str(value) if value not in (None, "", "unknown") else None


def _inline_runs(text: str) -> str:
    parts = re.split(r"(\*\*.+?\*\*|`[^`]+`)", text)
    runs = []
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            runs.append("<w:r><w:rPr><w:b/></w:rPr><w:t xml:space=\"preserve\">"
                        + escape(part[2:-2]) + "</w:t></w:r>")
        elif part.startswith("`") and part.endswith("`"):
            runs.append("<w:r><w:rPr><w:rFonts w:ascii=\"Consolas\" w:hAnsi=\"Consolas\"/>"
                        "</w:rPr><w:t xml:space=\"preserve\">" + escape(part[1:-1]) + "</w:t></w:r>")
        else:
            runs.append("<w:r><w:t xml:space=\"preserve\">" + escape(part) + "</w:t></w:r>")
    return "".join(runs) or "<w:r><w:t></w:t></w:r>"


def _paragraph(text: str, style: str | None = None) -> str:
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{properties}{_inline_runs(text)}</w:p>"


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    columns = max(len(row) for row in rows)
    borders = "".join(
        f'<w:{edge} w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    output = [
        '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>'
        '<w:tblLayout w:type="autofit"/><w:tblBorders>' + borders + '</w:tblBorders></w:tblPr>'
    ]
    for row_index, row in enumerate(rows):
        header = row_index == 0
        output.append("<w:tr>" + ('<w:trPr><w:tblHeader w:val="true"/></w:trPr>' if header else ""))
        for column in range(columns):
            value = row[column] if column < len(row) else ""
            cell_properties = '<w:tcPr><w:tcW w:w="0" w:type="auto"/>'
            if header:
                cell_properties += '<w:shd w:fill="EAF2FF" w:val="clear"/>'
            cell_properties += '</w:tcPr>'
            content = _inline_runs(value)
            if header:
                content = content.replace("<w:r>", "<w:r><w:rPr><w:b/></w:rPr>")
            output.append("<w:tc>" + cell_properties + "<w:p>" + content + "</w:p></w:tc>")
        output.append("</w:tr>")
    output.append("</w:tbl>")
    return "".join(output)


def _image_dimensions(content: bytes) -> tuple[int, int]:
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        width, height = struct.unpack(">II", content[16:24])
        return width, height
    raise ValueError("Unsupported Gold report image")


def _image_xml(image_index: int, filename: str, content: bytes) -> str:
    width, height = _image_dimensions(content)
    max_width = 5_760_000
    extent_x = min(max_width, width * 9525)
    extent_y = max(1, int(extent_x * height / width))
    relation_id = f"rIdImage{image_index}"
    return (
        f'<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{extent_x}" cy="{extent_y}"/>'
        f'<wp:docPr id="{image_index}" name="{escape(filename)}" descr="Gold 模拟现场照片"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="' + escape(filename) + '"/>'
        '<pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="' + relation_id + '"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr bwMode="auto">'
        '<a:xfrm><a:off x="0" y="0"/><a:ext cx="' + str(extent_x) + '" cy="' + str(extent_y) + '"/>'
        '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
    )


def _document_body(text: str, images: list[tuple[str, bytes]]) -> str:
    image_markers = {f"[[GOLD_IMAGE_{index}]]": (index + 1, filename, content)
                     for index, (filename, content) in enumerate(images)}
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line in image_markers:
            image_index, filename, content = image_markers[line]
            blocks.append(_image_xml(image_index, filename, content))
        elif line.strip().startswith("|") and line.strip().endswith("|"):
            table_rows = []
            while index < len(lines) and lines[index].strip().startswith("|") and lines[index].strip().endswith("|"):
                if not _is_table_separator(lines[index]):
                    table_rows.append(_table_cells(lines[index]))
                index += 1
            blocks.append(_table(table_rows))
            continue
        elif line.startswith("### "):
            blocks.append(_paragraph(line[4:].strip(), "Heading2"))
        elif line.startswith("## "):
            blocks.append(_paragraph(line[3:].strip(), "Heading1"))
        elif line.startswith("# "):
            blocks.append(_paragraph(line[2:].strip(), "Title"))
        elif line.startswith("> "):
            blocks.append(_paragraph(line[2:].strip(), "Quote"))
        elif line.startswith("- "):
            blocks.append(_paragraph("• " + line[2:].strip(), "ListParagraph"))
        elif line.startswith("```"):
            index += 1
            code_lines = []
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            blocks.extend(_paragraph(code_line, "CodeBlock") for code_line in code_lines)
        else:
            blocks.append(_paragraph(line))
        index += 1
    return "".join(blocks)


def _gold_photo_attachments(report: dict) -> list[tuple[str, bytes]]:
    source_metadata = report.get("source_metadata") if isinstance(report.get("source_metadata"), dict) else {}
    data_source = report.get("data_source") or source_metadata.get("data_source")
    if report.get("is_simulated") is not True or data_source != "local_gold_fixture:GOLD-01":
        return []
    facts = report.get("source_facts") if isinstance(report.get("source_facts"), dict) else {}
    attachments = facts.get("attachments") if isinstance(facts.get("attachments"), list) else []
    service_root = Path(__file__).resolve().parents[1]
    asset_root = (service_root / "tests" / "gold" / "yichang" / "assets").resolve()
    photos = []
    seen = set()
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if attachment.get("is_simulated") is not True:
            continue
        reference = attachment.get("file_ref") or attachment.get("fileRef")
        if not isinstance(reference, str) or not reference.replace("\\", "/").startswith(
            "tests/gold/yichang/assets/"
        ):
            continue
        path = (service_root / reference.replace("\\", "/")).resolve()
        if asset_root not in path.parents or path.suffix.lower() != ".png":
            continue
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        photos.append((path.name, path.read_bytes()))
        if len(photos) == 3:
            break
    return photos


def _docx_bytes(text: str, images: list[tuple[str, bytes]] | None = None) -> bytes:
    images = images or []
    paragraphs = _document_body(text, images)
    document = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" "
        "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\" "
        "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" "
        "xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        "<w:body>" + paragraphs +
        "<w:sectPr><w:pgSz w:w=\"12240\" w:h=\"15840\"/>"
        "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\"/>"
        "</w:sectPr></w:body></w:document>"
    )
    package = BytesIO()
    with ZipFile(package, "w", compression=ZIP_DEFLATED) as archive:
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        )
        for extension, content_type in (("png", "image/png"), ("jpg", "image/jpeg"), ("jpeg", "image/jpeg")):
            if any(Path(name).suffix.lower() == f".{extension}" for name, _ in images):
                content_types += f'<Default Extension="{extension}" ContentType="{content_type}"/>'
        content_types += "</Types>"
        archive.writestr(
            "[Content_Types].xml",
            content_types,
        )
        archive.writestr(
            "_rels/.rels",
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
            "</Relationships>",
        )
        archive.writestr(
            "word/styles.xml",
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<w:styles xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
            "<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\" w:eastAsia=\"Microsoft YaHei\"/>"
            "<w:sz w:val=\"22\"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after=\"120\" w:line=\"320\"/></w:pPr></w:pPrDefault></w:docDefaults>"
            "<w:style w:type=\"paragraph\" w:default=\"1\" w:styleId=\"Normal\"><w:name w:val=\"Normal\"/></w:style>"
            "<w:style w:type=\"paragraph\" w:styleId=\"Title\"><w:name w:val=\"Title\"/><w:basedOn w:val=\"Normal\"/><w:pPr><w:jc w:val=\"center\"/><w:spacing w:after=\"320\"/></w:pPr><w:rPr><w:b/><w:color w:val=\"1D3557\"/><w:sz w:val=\"36\"/></w:rPr></w:style>"
            "<w:style w:type=\"paragraph\" w:styleId=\"Heading1\"><w:name w:val=\"heading 1\"/><w:basedOn w:val=\"Normal\"/><w:pPr><w:outlineLvl w:val=\"0\"/><w:spacing w:before=\"280\" w:after=\"120\"/></w:pPr><w:rPr><w:b/><w:color w:val=\"1F4E79\"/><w:sz w:val=\"30\"/></w:rPr></w:style>"
            "<w:style w:type=\"paragraph\" w:styleId=\"Heading2\"><w:name w:val=\"heading 2\"/><w:basedOn w:val=\"Normal\"/><w:pPr><w:outlineLvl w:val=\"1\"/><w:spacing w:before=\"180\" w:after=\"80\"/></w:pPr><w:rPr><w:b/><w:color w:val=\"385D8A\"/><w:sz w:val=\"26\"/></w:rPr></w:style>"
            "<w:style w:type=\"paragraph\" w:styleId=\"Quote\"><w:name w:val=\"Quote\"/><w:basedOn w:val=\"Normal\"/><w:pPr><w:ind w:left=\"360\"/></w:pPr><w:rPr><w:i/><w:color w:val=\"666666\"/></w:rPr></w:style>"
            "<w:style w:type=\"paragraph\" w:styleId=\"ListParagraph\"><w:name w:val=\"List Paragraph\"/><w:basedOn w:val=\"Normal\"/><w:pPr><w:ind w:left=\"360\"/></w:pPr></w:style>"
            "<w:style w:type=\"paragraph\" w:styleId=\"CodeBlock\"><w:name w:val=\"Code Block\"/><w:basedOn w:val=\"Normal\"/><w:pPr><w:spacing w:after=\"0\"/></w:pPr><w:rPr><w:rFonts w:ascii=\"Consolas\" w:hAnsi=\"Consolas\"/><w:sz w:val=\"18\"/></w:rPr></w:style>"
            "</w:styles>",
        )
        archive.writestr("word/document.xml", document)
        if images:
            relationships = [
                f'<Relationship Id="rIdImage{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image{index}{Path(name).suffix.lower()}"/>'
                for index, (name, _) in enumerate(images, start=1)
            ]
            relationships.append(
                '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            )
            archive.writestr(
                "word/_rels/document.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(relationships) + "</Relationships>",
            )
            for index, (name, content) in enumerate(images, start=1):
                archive.writestr(f"word/media/image{index}{Path(name).suffix.lower()}", content)
        else:
            archive.writestr(
                "word/_rels/document.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                '</Relationships>',
            )
    return package.getvalue()


def _display_ids(values: object) -> str:
    if isinstance(values, (list, tuple)):
        items = [str(value) for value in values if value not in (None, "", "unknown")]
        return "、".join(items) if items else "unknown"
    return str(values) if values not in (None, "", "unknown") else "unknown"


async def get_yichang_document_status(document_id: str) -> dict:
    kb_id = YICHANG_KNOWLEDGE_BASES["evidence"]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{settings.rag_base_url.rstrip('/')}/api/v1/knowledge-bases/{kb_id}/documents/{document_id}/basic"
        )
        response.raise_for_status()
        return response.json()


async def archive_approved_report(report: dict, *, report_approved: bool, archive_approved: bool) -> dict:
    if report_approved is not True or archive_approved is not True:
        return {"status": "awaiting_report_and_archive_approval", "document_id": None}
    report_id = _java_report_id(report)
    if report_id is None:
        return {"status": "java_report_id_required", "document_id": None}
    report_text = report.get("report_text")
    if not isinstance(report_text, str) or not report_text.strip() or report_text.strip() == "待补充应急调查报告":
        return {"status": "report_text_required", "document_id": None}

    kb_id = YICHANG_KNOWLEDGE_BASES["evidence"]
    filename_id = re.sub(r"[^A-Za-z0-9._-]", "-", report_id)
    associations = report.get("associations") if isinstance(report.get("associations"), dict) else {}
    source_metadata = report.get("source_metadata") if isinstance(report.get("source_metadata"), dict) else {}
    metadata = {
        "report_id": report_id,
        "event_id": associations.get("event_id"),
        "task_ids": associations.get("task_ids", report.get("task_ids", [])),
        "is_simulated": report.get("is_simulated") is True or source_metadata.get("is_simulated") is True,
        "approval_mode": report.get("approval_mode"),
        "report_approved": True,
        "archive_approved": True,
        "data_source": source_metadata.get("data_source", report.get("data_source", "unknown")),
        "evidence_ids": report.get("evidence_ids", []),
        "feedback_ids": associations.get("feedback_ids", report.get("feedback_ids", [])),
        "missing_fields": report.get("missing_fields", []),
    }
    archive_revision = report.get("archive_revision")
    revision_suffix = "__indexed" if archive_revision == "indexed" else ""
    filename = f"宜昌GeoGuard复盘报告_{filename_id}{revision_suffix}.docx"
    preface = (
        "【Gold 模拟数据】本报告来自宜昌 GeoGuard Gold 端到端测试；"
        f"审批模式：{metadata['approval_mode'] or 'simulated_gold_test_harness'}。"
        "不代表真实人工复核或正式预警。\n\n"
        if metadata["is_simulated"]
        else "本文档由已审核报告写入 Geo-RAG 宜昌证据库。\n\n"
    )
    missing_fields = metadata["missing_fields"]
    missing_text = _display_ids(missing_fields) if missing_fields else "未记录缺失字段"
    readable_report = (
        "# 宜昌地质灾害事件复盘报告\n\n"
        + preface
        + report_text.strip()
        + "\n\n## 来源关联\n\n"
        + "| 信息项 | 记录 |\n| --- | --- |\n"
        + f"| 报告 ID | {_display_ids([report_id])} |\n"
        + f"| 事件 ID | {_display_ids([metadata['event_id']])} |\n"
        + f"| 任务 ID | {_display_ids(metadata['task_ids'])} |\n"
        + f"| 反馈 ID | {_display_ids(metadata['feedback_ids'])} |\n"
        + f"| 证据 ID | {_display_ids(metadata['evidence_ids'])} |\n"
        + f"| 数据来源 | {metadata['data_source'] or 'unknown'} |\n"
        + f"| 模拟状态 | {'Gold 模拟数据' if metadata['is_simulated'] else '非模拟记录'} |\n"
        + f"| 报告审核 | {'已批准' if metadata['report_approved'] else '未批准'} |\n"
        + f"| 入库审批 | {'已批准' if metadata['archive_approved'] else '未批准'} |\n"
        + f"| 缺失项 | {missing_text} |\n"
    )

    gold_photos = _gold_photo_attachments(report)
    if gold_photos:
        photo_section = "\n\n## 现场照片（Gold 模拟素材）\n\n"
        for index, (photo_filename, _content) in enumerate(gold_photos):
            photo_section += f"### 现场照片 {index + 1}：{photo_filename}\n[[GOLD_IMAGE_{index}]]\n\n"
        readable_report = readable_report.replace("\n\n## 来源关联\n", photo_section + "## 来源关联\n")
    report_bytes = _docx_bytes(readable_report, gold_photos)
    async with httpx.AsyncClient(timeout=60) as client:
        upload = await client.post(
            f"{settings.rag_base_url.rstrip('/')}/api/knowledge/files/upload",
            params={"kb_id": kb_id},
            files={"file": (filename, report_bytes,
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        if upload.status_code == 409:
            return {"status": "duplicate_content", "document_id": None, "knowledge_base_id": kb_id}
        upload.raise_for_status()
        staged = upload.json().get("file_path")
        if not isinstance(staged, str) or not staged.startswith("local-stage://"):
            return {"status": "upload_response_invalid", "document_id": None, "knowledge_base_id": kb_id}

        added = await client.post(
            f"{settings.rag_base_url.rstrip('/')}/api/knowledge/databases/{kb_id}/documents",
            json={"items": [staged], "params": {"auto_index": True}},
        )
        added.raise_for_status()
        result = added.json()
        processed = result.get("processed", [])
        document_id = processed[0].get("document_id") if processed else None
        task_id = result.get("task_id")
        if not document_id:
            return {"status": "ingest_not_submitted", "document_id": None,
                    "knowledge_base_id": kb_id, "failed": result.get("failed", [])}

        status = "submitted" if task_id else "added"
        for _ in range(15):
            basic = await client.get(
                f"{settings.rag_base_url.rstrip('/')}/api/v1/knowledge-bases/{kb_id}/documents/{document_id}/basic"
            )
            basic.raise_for_status()
            document = basic.json()
            if document.get("status") in {"indexed", "failed"}:
                status = document["status"]
                break
            await asyncio.sleep(2)

    return {
        "status": status,
        "document_id": document_id,
        "task_id": task_id,
        "knowledge_base_id": kb_id,
        "file_name": filename,
        "archive_revision": archive_revision or "initial",
    }
