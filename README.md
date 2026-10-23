# 地脉智控 · 宜昌地质灾害风险管理系统

本仓库提供地脉智控宜昌系统的前后端源码、容器化部署配置，以及运行所需的宜昌地图与风险数据。

## 默认登录账号

- 用户名：`admin`
- 密码：`dzzh@2025`
- 登录页会显示验证码，按页面提示输入。

该账号由本地部署配置创建，供首次登录使用。

## 本地部署

运行环境：Windows 10/11、Docker Desktop。首次启动需下载 Docker 镜像并构建服务。

1. 安装并启动 Docker Desktop。
2. 双击“启动地脉智控宜昌.bat”。
3. 浏览器打开系统后，使用上方账号登录。
4. 停止服务时，双击“停止地脉智控宜昌.bat”。

系统入口：

- 风险评价地图：http://127.0.0.1:5174/warning/risk-eval
- 动态风险一张图：http://127.0.0.1:5174/warning/risk-report
- 宜昌 AI 工作台：http://127.0.0.1:5174/ai-studio
- geo_rag 知识库：http://127.0.0.1:5175/?embed=rag#/extensions?tab=knowledge

若服务未就绪，可在仓库目录运行 `docker compose logs --tail=80` 查看日志。

## 系统组成

- `frontend/geo-guard-fe`：地脉智控宜昌业务前端。
- `frontend/geo-guard-fe/public/geo/yichang`：宜昌行政边界、道路、水系和三维地形数据。
- `frontend/geo_rag`：geo_rag 知识库界面。
- `ai/p6-service` 与 `data/p6`：宜昌斜坡单元静态、动态风险数据和查询服务。
- `ai/geo-agent-graph`：宜昌问答与业务流程接口。
- `ai/geo_rag`：geo_rag 检索服务。
- `backend/geo-guard-backend/local-auth-service`：本地登录与会话服务。
- `data/yichang-scenario`：宜昌业务流程场景资料。
- `compose.yaml` 与各服务 Dockerfile：容器构建和启动配置。

## 地图与数据

行政边界、道路、水系、地形和风险矢量瓦片随仓库提供。动态风险页面读取包内风险时片；启动服务不会自动联网更新气象数据。

水系数据按 OpenStreetMap ODbL 要求署名；地形数据署名见 `frontend/geo-guard-fe/public/geo/yichang/terrain/layer.json`。第三方依赖和上游许可见 `THIRD_PARTY_NOTICES.md`。

## AI 与知识库

AI 工作台连接包内宜昌问答服务，并提供 geo_rag 知识库入口。首次部署时知识库为空；添加宜昌资料并配置模型服务后，可使用基于知识库的问答。未配置模型时，风险地图和包内风险数据仍可使用。

## 服务端口

| 服务 | 本机地址 |
|---|---|
| 地脉智控前端 | `127.0.0.1:5174` |
| geo_rag 知识库 | `127.0.0.1:5175` |

登录、问答、P6 和数据服务通过 Docker 内部网络通信。
