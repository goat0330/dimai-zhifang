# 第三方许可说明

geo_rag 界面和后端保留所用上游组件的许可证文本，见 `frontend/geo_rag/THIRD_PARTY_LICENSES.md`、`ai/geo_rag/vendor/yuxi/LICENSE` 和 `ai/geo_rag/app/yuxi_port/ragflow_like/LICENSE.txt`。后端 vendored 源码版本为 v0.7.3。依赖版本记录在 `pnpm-lock.yaml` 和 `uv.lock` 中，构建时按锁定版本安装。

各依赖仍受其原始许可证约束。重新分发或修改依赖时，请保留对应许可证和版权声明。
## Java 后端

- `backend/geo-guard-backend/framework/LICENSE.RUOYI-VUE-PLUS`：RuoYi-Vue-Plus 上游 MIT 许可证。
- `backend/geo-guard-backend/framework/LICENSE-IP2REGION.md`：ip2region 上游 Apache-2.0 OR MIT 双许可证；后端源码包内保留了对应的 IP 区域数据库文件。
- Java 依赖版本记录在各模块的 `pom.xml` 中；源文件已有的版权和许可声明保持原样。
