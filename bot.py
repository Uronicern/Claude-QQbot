"""QQ Bot 客户端 — 处理 C2C 私聊消息"""

import asyncio

import botpy
from botpy.message import C2CMessage
import structlog

from claude_bridge import ClaudeBridge
from config import Settings
from message_utils import split_message

logger = structlog.get_logger()


AVAILABLE_MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}

MODEL_ALIASES = {v: k for k, v in AVAILABLE_MODELS.items()}


class QQBot(botpy.Client):
    def __init__(self, settings: Settings, claude_bridge: ClaudeBridge):
        intents = botpy.Intents(public_messages=True)
        super().__init__(intents=intents, is_sandbox=settings.qq_sandbox)
        self.settings = settings
        self.claude = claude_bridge
        self._msg_seq: dict[str, int] = {}
        self._user_models: dict[str, str] = {}  # 每用户模型选择

    async def on_ready(self):
        logger.info("QQ Bot 已上线", bot=f"{self.robot.name}")

    async def on_c2c_message_create(self, message: C2CMessage):
        user_openid = message.author.user_openid
        content = (message.content or "").strip()

        if not content:
            return

        logger.info("收到私聊消息", user=user_openid[:8], content=content[:50])

        # 鉴权
        allowed = self.settings.allowed_user_list
        if allowed and user_openid not in allowed:
            await self._reply(message, "未授权的用户。")
            return

        # 命令路由
        if content.startswith("/"):
            await self._handle_command(message, content)
            return

        # 普通消息 → Claude
        await self._handle_message(message, content)

    async def _handle_command(self, message: C2CMessage, content: str):
        cmd = content.split()[0].lower()
        user_openid = message.author.user_openid

        if cmd == "/new":
            self.claude.session_manager.reset_session(user_openid)
            await self._reply(message, "会话已重置。下一条消息将开始新对话。")

        elif cmd == "/model":
            parts = content.split()
            if len(parts) < 2:
                # 显示当前模型和可选列表
                current = self._user_models.get(user_openid, self.settings.claude_model)
                alias = MODEL_ALIASES.get(current, current)
                lines = [
                    f"当前模型: {alias} ({current})",
                    "",
                    "可用模型:",
                    "  /model haiku — Claude Haiku 4.5 (快速便宜)",
                    "  /model sonnet — Claude Sonnet 4.6 (均衡)",
                    "  /model opus — Claude Opus 4.6 (最强)",
                ]
                await self._reply(message, "\n".join(lines))
            else:
                name = parts[1].lower()
                if name in AVAILABLE_MODELS:
                    self._user_models[user_openid] = AVAILABLE_MODELS[name]
                    await self._reply(message, f"已切换到 {name} ({AVAILABLE_MODELS[name]})")
                else:
                    await self._reply(message, f"未知模型: {name}\n可选: haiku / sonnet / opus")

        elif cmd == "/status":
            info = self.claude.session_manager.get_session_info(user_openid)
            if not info:
                await self._reply(message, "当前没有活跃会话。")
            else:
                text = (
                    f"会话状态:\n"
                    f"  会话ID: {info['session_id']}\n"
                    f"  创建时间: {info['created']}\n"
                    f"  持续时间: {info['duration']}\n"
                    f"  消息数: {info['messages']}\n"
                    f"  Claude轮次: {info['turns']}\n"
                    f"  费用: {info['cost']}"
                )
                await self._reply(message, text)

        elif cmd == "/help":
            await self._reply(
                message,
                "可用命令:\n"
                "  /new — 重置会话，开始新对话\n"
                "  /model — 查看/切换模型 (haiku/sonnet/opus)\n"
                "  /status — 查看当前会话状态\n"
                "  /help — 显示此帮助\n\n"
                "直接发送消息即可与 Claude 对话。",
            )

        else:
            # 未知命令，当作普通消息转发给 Claude
            await self._handle_message(message, content)

    async def _handle_message(self, message: C2CMessage, content: str):
        user_openid = message.author.user_openid

        # 调用 Claude（使用用户选择的模型）
        model = self._user_models.get(user_openid)
        response = await self.claude.query(user_openid, content, model=model)

        logger.info(
            "Claude 响应完成",
            user=user_openid[:8],
            cost=f"${response.cost:.4f}",
            duration=f"{response.duration_ms}ms",
            is_error=response.is_error,
        )

        # 分割长消息并发送
        chunks = split_message(response.content)
        for i, chunk in enumerate(chunks):
            await self._reply(message, chunk)
            if i < len(chunks) - 1:
                await asyncio.sleep(0.3)  # 避免 QQ 限流

    async def _reply(self, message: C2CMessage, text: str):
        user_openid = message.author.user_openid

        # 递增消息序列号
        seq = self._msg_seq.get(user_openid, 0) + 1
        self._msg_seq[user_openid] = seq

        try:
            await message._api.post_c2c_message(
                openid=user_openid,
                msg_type=0,
                content=text,
                msg_id=message.id,
                msg_seq=seq,
            )
        except Exception as e:
            logger.error("发送消息失败", user=user_openid[:8], error=str(e))
