"""QQ Bot 客户端 — 处理 C2C 私聊消息"""

import asyncio
import base64
import time

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

# 消息去重缓存保留时间（秒）
DEDUP_TTL = 60


class QQBot(botpy.Client):
    def __init__(self, settings: Settings, claude_bridge: ClaudeBridge):
        intents = botpy.Intents(public_messages=True)
        super().__init__(intents=intents, is_sandbox=settings.qq_sandbox)
        self.settings = settings
        self.claude = claude_bridge
        self._msg_seq: dict[str, int] = {}
        self._user_models: dict[str, str] = {}
        self._processed_msgs: dict[str, float] = {}  # msg_id -> timestamp

    async def on_ready(self):
        name = getattr(self, "robot", None)
        logger.info("QQ Bot 已上线", bot=name.name if name else "unknown")

    async def on_c2c_message_create(self, message: C2CMessage):
        # 消息去重
        if self._is_duplicate(message.id):
            return

        user_openid = message.author.user_openid
        content = (message.content or "").strip()

        # 检查是否有图片附件
        image_blocks = await self._extract_images(message)

        if not content and not image_blocks:
            return

        logger.info("收到私聊消息", user=user_openid[:8], content=content[:50],
                     images=len(image_blocks))

        # 鉴权
        allowed = self.settings.allowed_user_list
        if allowed and user_openid not in allowed:
            await self._reply(message, "未授权的用户。")
            return

        # 命令路由（仅纯文本命令）
        if content.startswith("/") and not image_blocks:
            await self._handle_command(message, content)
            return

        # 构建 prompt（可能包含图片）
        if image_blocks:
            prompt = image_blocks.copy()
            if content:
                prompt.append({"type": "text", "text": content})
            else:
                prompt.append({"type": "text", "text": "请分析这张图片。"})
        else:
            prompt = content

        # 消息 → Claude
        await self._handle_message(message, prompt)

    async def _extract_images(self, message: C2CMessage) -> list[dict]:
        """从消息附件中提取图片，下载并转为 base64 content blocks。"""
        blocks = []
        attachments = getattr(message, "attachments", None) or []
        for att in attachments:
            ct = getattr(att, "content_type", "") or ""
            url = getattr(att, "url", None)
            if not ct.startswith("image/") or not url:
                continue
            # 确保 URL 有协议前缀
            if url.startswith("//"):
                url = "https:" + url
            elif not url.startswith("http"):
                url = "https://" + url
            try:
                import asyncio
                proc = await asyncio.create_subprocess_exec(
                    "curl", "-sL", "--max-time", "10", "--max-filesize", "5242880", url,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                data, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
                if data and len(data) > 100:
                    b64 = base64.standard_b64encode(data).decode("ascii")
                    media_type = ct.split(";")[0].strip()
                    blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    })
                    logger.info("图片下载成功", size=len(data), type=media_type)
            except Exception as e:
                logger.error("图片下载失败", error=str(e))
        return blocks

    def _is_duplicate(self, msg_id: str) -> bool:
        """去重：跳过已处理的消息，同时清理过期记录。"""
        now = time.time()
        # 清理过期记录
        expired = [k for k, t in self._processed_msgs.items() if now - t > DEDUP_TTL]
        for k in expired:
            del self._processed_msgs[k]

        if msg_id in self._processed_msgs:
            return True
        self._processed_msgs[msg_id] = now
        return False

    async def _handle_command(self, message: C2CMessage, content: str):
        cmd = content.split()[0].lower()
        user_openid = message.author.user_openid

        if cmd == "/new":
            self.claude.session_manager.reset_session(user_openid)
            await self._reply(message, "会话已重置。下一条消息将开始新对话。")

        elif cmd == "/model":
            parts = content.split()
            if len(parts) < 2:
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
                current_model = self._user_models.get(user_openid, self.settings.claude_model)
                alias = MODEL_ALIASES.get(current_model, current_model)
                text = (
                    f"会话状态:\n"
                    f"  模型: {alias} ({current_model})\n"
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

    async def _handle_message(self, message: C2CMessage, prompt: str | list):
        user_openid = message.author.user_openid

        # 检查会话是否过期重建
        _, is_expired = self.claude.session_manager.get_or_create(user_openid)
        if is_expired:
            await self._reply(message, "[提示] 上次会话已过期，已自动开始新对话。")

        # 调用 Claude（使用用户选择的模型）
        model = self._user_models.get(user_openid)
        response = await self.claude.query(user_openid, prompt, model=model)

        logger.info(
            "Claude 响应完成",
            user=user_openid[:8],
            cost=f"${response.cost:.4f}",
            duration=f"{response.duration_ms}ms",
            is_error=response.is_error,
        )

        # 分割长消息并发送
        chunks = split_message(response.content)
        if not chunks:
            chunks = ["(空响应)"]

        for i, chunk in enumerate(chunks):
            success = await self._reply(message, chunk)
            if not success:
                break
            if i < len(chunks) - 1:
                await asyncio.sleep(1.0)  # QQ 限流保护

    async def _reply(self, message: C2CMessage, text: str) -> bool:
        """发送回复，返回是否成功。"""
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
            return True
        except Exception as e:
            logger.error("发送消息失败", user=user_openid[:8], error=str(e))
            return False
