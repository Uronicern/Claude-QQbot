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

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})
        self._truncate()

    def _truncate(self):
        """截断历史，确保首条消息为 user 角色（API 要求）。"""
        if len(self.messages) > MAX_HISTORY:
            self.messages = self.messages[-MAX_HISTORY:]
        # 确保第一条是 user 消息
        while self.messages and self.messages[0]["role"] != "user":
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

        # 过期或不存在，创建新的
        is_new = session is not None  # 有旧的说明是过期重建
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
        """清理所有过期会话，防止内存泄漏。"""
        now = datetime.now()
        expired = [k for k, v in self._sessions.items() if (now - v.last_used) >= self._timeout]
        for k in expired:
            del self._sessions[k]
