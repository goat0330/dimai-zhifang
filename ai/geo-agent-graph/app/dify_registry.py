"""Server-side configuration mapping for the five Yichang agents."""

from dataclasses import dataclass, field

from .config import settings


@dataclass(frozen=True)
class DifyApp:
    agent_id: str
    app_name: str
    app_mode: str
    api_key: str = field(repr=False)
    app_role: str = "primary"
    registry_id: str = ""


_AGENT_APPS = {
    "A1": ("A1", "primary", "dify_a1_"),
    "A2": ("A2", "primary", "dify_a2_"),
    "A3": ("A3", "primary", "dify_a3_"),
    "A3_ALERT": ("A3", "alert", "dify_a3_alert_"),
    "A4": ("A4", "primary", "dify_a4_"),
    "A4_PLAN": ("A4", "plan", "dify_a4_plan_"),
    "A5": ("A5", "primary", "dify_a5_"),
}


def _secret_value(value: object) -> str:
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    return str(value or "").strip()


def get_dify_app(agent_id: str, config=settings) -> DifyApp:
    registry_id = str(agent_id).strip().upper()
    entry = _AGENT_APPS.get(registry_id)
    if entry is None:
        raise ValueError(f"Unknown Yichang Dify agent: {agent_id}")
    canonical_id, app_role, prefix = entry
    return DifyApp(
        agent_id=canonical_id,
        app_name=str(getattr(config, f"{prefix}app_name")),
        app_mode=str(getattr(config, f"{prefix}app_mode")),
        api_key=_secret_value(getattr(config, f"{prefix}api_key")),
        app_role=app_role,
        registry_id=registry_id,
    )


def dify_configured(agent_id: str, config=settings) -> bool:
    try:
        app = get_dify_app(agent_id, config)
    except ValueError:
        return False
    return bool(str(getattr(config, "dify_base_url", "")).strip() and app.api_key)


def list_dify_apps(config=settings) -> list[dict]:
    base_url_set = bool(str(getattr(config, "dify_base_url", "")).strip())
    return [
        {
            "agent_id": (app := get_dify_app(registry_id, config)).agent_id,
            "registry_id": registry_id,
            "app_role": app.app_role,
            "app_name": app.app_name,
            "app_mode": app.app_mode,
            "configured": bool(base_url_set and app.api_key),
        }
        for registry_id in _AGENT_APPS
    ]
