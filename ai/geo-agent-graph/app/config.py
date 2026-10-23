from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    rag_base_url: str = "http://127.0.0.1:8010"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    rag_top_k: int = 5
    java_backend_base_url: str = ""
    java_backend_bearer_token: str = ""
    dify_base_url: str = "https://api.dify.ai"
    dify_timeout_seconds: float = 60.0
    dify_response_mode: str = "blocking"
    dify_a1_app_name: str = "Geo-Chatflow-v0.9.9"
    dify_a1_app_mode: str = "advanced-chat"
    dify_a1_api_key: SecretStr = SecretStr("")
    dify_a2_app_name: str = "GEO识图-多图汇总"
    dify_a2_app_mode: str = "advanced-chat"
    dify_a2_api_key: SecretStr = SecretStr("")
    dify_a3_app_name: str = "趋势预测工作流"
    dify_a3_app_mode: str = "advanced-chat"
    dify_a3_api_key: SecretStr = SecretStr("")
    dify_a3_alert_app_name: str = "地灾应急告警"
    dify_a3_alert_app_mode: str = "advanced-chat"
    dify_a3_alert_api_key: SecretStr = SecretStr("")
    dify_a4_app_name: str = "Geo-AI-analyse"
    dify_a4_app_mode: str = "advanced-chat"
    dify_a4_api_key: SecretStr = SecretStr("")
    dify_a4_plan_app_name: str = "宜昌 A4 处置方案审核"
    dify_a4_plan_app_mode: str = "advanced-chat"
    dify_a4_plan_api_key: SecretStr = SecretStr("")
    dify_a5_app_name: str = "应急调查报告v2"
    dify_a5_app_mode: str = "advanced-chat"
    dify_a5_api_key: SecretStr = SecretStr("")
    p6_api_base_url: str = "http://127.0.0.1:8017"
    p6_timeout_seconds: float = 8.0
    yichang_scenario_db_path: str = str(PACKAGE_ROOT / "ai" / "geo-agent-graph" / ".runtime" / "yichang_scenario.sqlite3")
    yichang_scenario_fixture_dir: str = str(PACKAGE_ROOT / "data" / "yichang-scenario")
    cors_allowed_origins: str = "http://127.0.0.1:5174,https://127.0.0.1:5174,http://localhost:5174"

settings = Settings()
