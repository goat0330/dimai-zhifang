# 地脉智控 · 宜昌演示包

本包用于运行地脉智控宜昌单场演示，展示秭归监测告警、风险研判、处置任务和恢复跟踪。

演示数据保存在本地，属于演示场景数据，不代表实时监测或现场处置记录。主流程不依赖外部模型服务；需要外部智能分析的按钮须另行配置对应服务。

## 启动方式

运行环境：Windows 10/11、Docker Desktop。首次启动需要网络下载容器基础镜像和项目依赖，时间取决于网络和电脑配置。

1. 安装并启动 Docker Desktop。
2. 双击“启动地脉智控宜昌演示.bat”。
3. 等待服务启动，浏览器会打开宜昌演示页面。
4. 结束演示时双击“停止地脉智控宜昌演示.bat”。

宜昌演示地址：http://127.0.0.1:5174/demo  
geo_rag 地址：http://127.0.0.1:5175/

启动脚本会尝试启动 Docker Desktop，并等待主要页面和业务服务就绪。若服务没有打开，可在本目录运行“docker compose logs --tail=80”查看启动信息。

## 目录内容

- frontend/geo-guard-fe：地脉智控宜昌演示界面。
- frontend/geo_rag：geo_rag 知识检索界面。
- ai/geo-agent-graph：宜昌演示流程服务。
- ai/geo_rag：geo_rag 检索服务。
- data/demo-gold：宜昌秭归演示场景数据。
- backend/geo-guard-backend：完整 Java 业务后端源码、框架模块和本地构建/初始化脚本。

该 Java 后端源码单独保留在 backend/geo-guard-backend 中；当前宜昌演示的 Docker Compose 不启动这套 Java 服务，演示所需的前后端服务由本目录中的 Compose 配置启动。
- compose.yaml 与各目录中的 Dockerfile：服务构建和启动配置。
- 启动地脉智控宜昌演示.bat、停止地脉智控宜昌演示.bat：Windows 启停入口。

各服务端口仅绑定到本机回环地址。业务演示数据和知识库文件保存在 Docker 数据卷中；停止脚本不会清除这些数据。
