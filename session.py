"""会话管理 — 按 QQ user_openid 管理 Claude 会话"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from config import Settings


@dataclass
class ClaudeSession:
    user_openid: str
    session_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    total_cost: float = 0.0
    total_turns: int = 0
    message_count: int = 0
    messages: list[dict] = field(default_factory=list)  # 对话历史

    def touch(self):
        self.last_used = datetime.now()
        self.message_count += 1

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})
        # 保留最近 40 条消息，防止 token 过多
        if len(self.messages) > 40:
            self.messages = self.messages[-40:]

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})


class SessionManager:
    def __init__(self, settings: Settings):
        self._sessions: dict[str, ClaudeSession] = {}
        self._timeout = timedelta(hours=settings.session_timeout_hours)

    def get_or_create(self, user_openid: str) -> ClaudeSession:
        session = self._sessions.get(user_openid)
        if session and (datetime.now() - session.last_used) < self._timeout:
            session.touch()
            return session
        # 过期或不存在，创建新的
        session = ClaudeSession(user_openid=user_openid)
        self._sessions[user_openid] = session
        return session

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
