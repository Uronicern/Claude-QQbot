"""Claude 集成 — 通过 Anthropic SDK 直接调用 API"""

import asyncio
import time
from dataclasses import dataclass

import structlog
from anthropic import AsyncAnthropic

from config import Settings
from message_utils import format_error
from session import SessionManager

logger = structlog.get_logger()

SYSTEM_PROMPT = (
    "你是一个通过 QQ 聊天的编程助手。"
    "请用简洁的中文回复，注意消息长度不要太长。"
    "如果需要展示代码，尽量控制在合理长度内。"
)

# 各模型的 (input_price, output_price) 每百万 token
MODEL_PRICING = {
    "claude-haiku-4-5-20251001": (0.0008, 0.004),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-opus-4-6": (0.015, 0.075),
}
DEFAULT_PRICING = (0.003, 0.015)  # 未知模型用 Sonnet 价格


@dataclass
class ClaudeResponse:
    content: str
    session_id: str | None = None
    cost: float = 0.0
    duration_ms: int = 0
    is_error: bool = False


class ClaudeBridge:
    def __init__(self, settings: Settings, session_manager: SessionManager):
        self.settings = settings
        self.session_manager = session_manager
        self._user_locks: dict[str, asyncio.Lock] = {}

        # 初始化 Anthropic 客户端
        client_kwargs = {}
        if settings.anthropic_api_key:
            client_kwargs["api_key"] = settings.anthropic_api_key.get_secret_value()
        if settings.anthropic_base_url:
            client_kwargs["base_url"] = settings.anthropic_base_url

        self.client = AsyncAnthropic(**client_kwargs)

    async def query(self, user_openid: str, prompt: str, model: str | None = None) -> ClaudeResponse:
        """向 Claude 发送查询并返回响应。per-user 加锁防止并发。"""
        lock = self._user_locks.setdefault(user_openid, asyncio.Lock())
        async with lock:
            return await self._do_query(user_openid, prompt, model)

    async def _do_query(self, user_openid: str, prompt: str, model: str | None) -> ClaudeResponse:
        start_time = time.monotonic()
        session, _ = self.session_manager.get_or_create(user_openid)
        use_model = model or self.settings.claude_model

        try:
            session.add_user_message(prompt)

            response = await self.client.messages.create(
                model=use_model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=session.messages,
                timeout=self.settings.claude_timeout_seconds,
            )

            # 提取文本内容
            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            if not content:
                content = "(Claude 未返回内容)"

            session.add_assistant_message(content)

            duration_ms = int((time.monotonic() - start_time) * 1000)

            # 按模型计费
            input_price, output_price = MODEL_PRICING.get(use_model, DEFAULT_PRICING)
            cost = (response.usage.input_tokens * input_price + response.usage.output_tokens * output_price) / 1_000_000

            self.session_manager.update_session(
                user_openid,
                session_id=response.id,
                cost=cost,
                turns=1,
            )

            return ClaudeResponse(
                content=content,
                session_id=response.id,
                cost=cost,
                duration_ms=duration_ms,
            )

        except Exception as error:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error("Claude 查询失败", error=str(error), type=type(error).__name__)

            # 移除失败的用户消息
            if session.messages and session.messages[-1]["role"] == "user":
                session.messages.pop()

            return ClaudeResponse(
                content=format_error(error),
                duration_ms=duration_ms,
                is_error=True,
            )
