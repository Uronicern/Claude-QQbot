"""配置管理 — 从 .env 文件加载设置"""

from pathlib import Path
from typing import Optional

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # QQ Bot
    qq_app_id: str
    qq_app_secret: SecretStr
    qq_sandbox: bool = True

    # Claude
    anthropic_api_key: Optional[SecretStr] = None
    anthropic_base_url: Optional[str] = None
    claude_model: str = "claude-sonnet-4-6"
    claude_timeout_seconds: int = 300
    claude_max_tool_rounds: int = 20

    # 项目
    working_directory: Path
    session_timeout_hours: int = 24
    allowed_users: Optional[str] = None

    # 日志
    log_level: str = "INFO"

    @field_validator("working_directory")
    @classmethod
    def validate_working_directory(cls, v: Path) -> Path:
        v = v.resolve()
        if not v.exists():
            raise ValueError(f"工作目录不存在: {v}")
        if not v.is_dir():
            raise ValueError(f"路径不是目录: {v}")
        return v

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def empty_api_key_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("anthropic_base_url", mode="before")
    @classmethod
    def empty_base_url_to_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v if v else None
        return v

    @property
    def allowed_user_list(self) -> list[str] | None:
        if not self.allowed_users:
            return None
        return [u.strip() for u in self.allowed_users.split(",") if u.strip()]
