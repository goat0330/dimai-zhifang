export async function askYichangKnowledge(query, { conversationId = '', signal } = {}) {
  const response = await fetch('/geo-ai-agent/api/v1/yichang/qa', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      context: conversationId ? { conversation_id: conversationId } : {},
    }),
    signal,
  })
  const result = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(result.detail || result.message || `知识问答服务请求失败（HTTP ${response.status}）`)
  }
  return result
}

export function formatYichangAnswer(result = {}) {
  const answer = String(result.answer || '').trim() || '本次未返回可用回答。'
  return answer
}

export function mapYichangEvidence(evidence = []) {
  if (!Array.isArray(evidence)) return []

  return evidence.slice(0, 6).map((item) => {
    const spans = Array.isArray(item.source_spans) ? item.source_spans : []
    const page = Number(item.page || spans.find((span) => span?.page)?.page)
    const knowledgeBaseId = item.knowledge_base_id
    const documentId = item.document_id
    const sourceUrl = knowledgeBaseId && documentId
      ? `/api/dizai/ai/rag/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents/${encodeURIComponent(documentId)}/download`
      : ''

    return {
      source: item.file_name || item.document_id || item.evidence_id || '宜昌知识库资料',
      title: item.file_name || '宜昌知识库资料',
      document_name: item.file_name || '',
      document_id: documentId,
      dataset_id: knowledgeBaseId,
      knowledge_base_label: item.knowledge_base_label || '',
      page: Number.isInteger(page) && page > 0 ? page : null,
      pages: Number.isInteger(page) && page > 0 ? [page] : [],
      source_url: sourceUrl,
      bboxes: spans.filter((span) => Array.isArray(span?.bbox)),
      content: item.text || '',
    }
  })
}
