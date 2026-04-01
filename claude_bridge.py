"""Claude 集成 — 通过 Anthropic SDK 调用 API，支持 tool use"""

import asyncio
import time
from dataclasses import dataclass

import structlog
from anthropic import AsyncAnthropic

from config import Settings
from message_utils import format_error
from session import SessionManager
from tools import TOOL_DEFINITIONS, execute_tool

logger = structlog.get_logger()

SYSTEM_PROMPT = (
    "你是一个通过 QQ 聊天的全能编程助手，拥有完整的电脑操作能力。\n"
    "你可以使用以下工具：\n"
    "- read_file / write_file / edit_file / list_directory / search_files — 文件操作\n"
    "- run_command — 执行任意 shell 命令\n"
    "- fetch_url — 访问网页和 API\n"
    "- git_command — Git 操作\n"
    "- system_info / manage_process — 系统和进程管理\n"
    "- screenshot / analyze_image — 截屏和图片分析\n"
    "- clipboard — 剪贴板读写\n"
    "- open_app — 打开应用、文件或 URL\n\n"
    "当用户要求操作文件、执行命令、访问网络或管理系统时，直接使用工具完成。\n"
    "用户发送的图片你可以直接看到并分析。\n"
    "请用简洁的中文回复，代码尽量控制长度。"
)

# 各模型的 (input_price, output_price) 每百万 token
MODEL_PRICING = {
    "claude-haiku-4-5-20251001": (0.0008, 0.004),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-opus-4-6": (0.015, 0.075),
}
DEFAULT_PRICING = (0.003, 0.015)


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

        client_kwargs = {}
        if settings.anthropic_api_key:
            client_kwargs["api_key"] = settings.anthropic_api_key.get_secret_value()
        if settings.anthropic_base_url:
            client_kwargs["base_url"] = settings.anthropic_base_url
        self.client = AsyncAnthropic(**client_kwargs)

    async def query(self, user_openid: str, prompt: str | list, model: str | None = None) -> ClaudeResponse:
        """prompt 可以是字符串或 content blocks 列表（含图片时）。"""
        lock = self._user_locks.setdefault(user_openid, asyncio.Lock())
        async with lock:
            return await self._do_query(user_openid, prompt, model)

    async def _do_query(self, user_openid: str, prompt: str | list, model: str | None) -> ClaudeResponse:
        start_time = time.monotonic()
        session, _ = self.session_manager.get_or_create(user_openid)
        use_model = model or self.settings.claude_model
        total_input_tokens = 0
        total_output_tokens = 0

        try:
            session.add_user_message(prompt)

            # Tool use 循环
            for round_num in range(self.settings.claude_max_tool_rounds):
                response = await self.client.messages.create(
                    model=use_model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=session.messages,
                    tools=TOOL_DEFINITIONS,
                    timeout=self.settings.claude_timeout_seconds,
                )

                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

                # 检查是否有 tool_use
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

                if not tool_use_blocks:
                    # 没有工具调用，提取文本返回
                    content = self._extract_text(response.content)
                    session.add_assistant_message(content)
                    break

                # 有工具调用：保存 assistant 消息（含 tool_use blocks）
                # 需要序列化 content blocks
                assistant_content = []
                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                session.add_assistant_message(assistant_content)

                # 执行所有工具并收集结果
                tool_results = []
                for block in tool_use_blocks:
                    logger.info("执行工具", tool=block.name, round=round_num + 1)
                    result = await execute_tool(
                        block.name, block.input, self.settings.working_directory
                    )
                    # result 可以是字符串或 content blocks 列表（截屏/图片工具）
                    if isinstance(result, list):
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        })

                # 添加 tool_result 消息
                session.messages.append({"role": "user", "content": tool_results})

                logger.info("工具执行完成", round=round_num + 1, tools=len(tool_use_blocks))
            else:
                # 达到最大轮数
                content = self._extract_text(response.content)
                if not content:
                    content = "(达到最大工具调用轮数)"
                session.add_assistant_message(content)

            # 提取最终文本
            final_content = ""
            last_msg = session.messages[-1]
            if last_msg["role"] == "assistant":
                c = last_msg["content"]
                if isinstance(c, str):
                    final_content = c
                elif isinstance(c, list):
                    final_content = " ".join(
                        b["text"] for b in c if isinstance(b, dict) and b.get("type") == "text"
                    )

            if not final_content:
                final_content = "(Claude 未返回文本内容)"

            duration_ms = int((time.monotonic() - start_time) * 1000)
            input_price, output_price = MODEL_PRICING.get(use_model, DEFAULT_PRICING)
            cost = (total_input_tokens * input_price + total_output_tokens * output_price) / 1_000_000

            self.session_manager.update_session(
                user_openid, session_id=response.id, cost=cost, turns=1,
            )

            return ClaudeResponse(
                content=final_content, session_id=response.id,
                cost=cost, duration_ms=duration_ms,
            )

        except Exception as error:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error("Claude 查询失败", error=str(error), type=type(error).__name__)
            # 移除失败的用户消息
            if session.messages and session.messages[-1].get("role") == "user":
                session.messages.pop()
            return ClaudeResponse(
                content=format_error(error), duration_ms=duration_ms, is_error=True,
            )

    @staticmethod
    def _extract_text(content_blocks) -> str:
        return "".join(b.text for b in content_blocks if b.type == "text")
