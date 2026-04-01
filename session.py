"""会话管理 — 按 QQ user_openid 管理 Claude 会话"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from config import Settings

MAX_HISTORY = 40  # 最大保留消息条数


@dataclass
class ClaudeSession:
    user_openid: str
    session_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    total_cost: float = 0.0
    total_turns: int = 0
    message_count: int = 0
    messages: list[dict] = field(default_factory=list)

    def touch(self):
        self.last_used = datetime.now()
        self.message_count += 1

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})
        self._truncate()

    def add_assistant_message(self, content):
        """content 可以是字符串或 content blocks 列表（tool_use 场景）。"""
        self.messages.append({"role": "assistant", "content": content})
        self._truncate()

    def add_tool_result(self, tool_use_id: str, result: str):
        """添加工具执行结果。"""
        self.messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                }
            ],
        })

    def _truncate(self):
        """截断历史，确保不破坏 tool_use/tool_result 配对。"""
        if len(self.messages) <= MAX_HISTORY:
            return

        self.messages = self.messages[-MAX_HISTORY:]

        # 确保第一条是 user 消息（非 tool_result）
        while self.messages:
            msg = self.messages[0]
            if msg["role"] == "user":
                content = msg.get("content")
                # 如果是 tool_result 列表，不能作为开头
                if isinstance(content, list) and any(
                    b.get("type") == "tool_result" for b in content if isinstance(b, dict)
                ):
                    self.messages.pop(0)
                    continue
                break
            else:
                self.messages.pop(0)


class SessionManager:
    def __init__(self, settings: Settings):
        self._sessions: dict[str, ClaudeSession] = {}
        self._timeout = timedelta(hours=settings.session_timeout_hours)

    def get_or_create(self, user_openid: str) -> tuple[ClaudeSession, bool]:
        """返回 (session, is_new)，is_new=True 表示会话过期被重建。"""
        self._cleanup_expired()

        session = self._sessions.get(user_openid)
        if session and (datetime.now() - session.last_used) < self._timeout:
            session.touch()
            return session, False

        is_new = session is not None
        session = ClaudeSession(user_openid=user_openid)
        self._sessions[user_openid] = session
        return session, is_new

    def update_session(self, user_openid: str, session_id: str | None, cost: float, turns: int):
        session = self._sessions.get(user_openid)
        if not session:
            return
        if session_id:
            session.session_id = session_id
        session.total_cost += cost
        session.total_turns += turns

    def reset_session(self, user_openid: str):
        self._sessions.pop(user_openid, None)

    def get_session_info(self, user_openid: str) -> dict | None:
        session = self._sessions.get(user_openid)
        if not session:
            return None
        elapsed = datetime.now() - session.created_at
        return {
            "session_id": session.session_id or "(等待首次响应)",
            "created": session.created_at.strftime("%H:%M:%S"),
            "duration": str(elapsed).split(".")[0],
            "messages": session.message_count,
            "turns": session.total_turns,
            "cost": f"${session.total_cost:.4f}",
        }

    def _cleanup_expired(self):
        now = datetime.now()
        expired = [k for k, v in self._sessions.items() if (now - v.last_used) >= self._timeout]
        for k in expired:
            del self._sessions[k]
