"""Claude Code QQ Bot — 入口"""

import logging

import structlog

from bot import QQBot
from claude_bridge import ClaudeBridge
from config import Settings
from session import SessionManager


def setup_logging(log_level: str = "INFO"):
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def main():
    settings = Settings()
    setup_logging(settings.log_level)

    logger = structlog.get_logger()
    logger.info("启动 Claude Code QQ Bot")
    logger.info("工作目录", path=str(settings.working_directory))
    logger.info("沙箱模式", sandbox=settings.qq_sandbox)

    session_manager = SessionManager(settings)
    claude_bridge = ClaudeBridge(settings, session_manager)
    bot = QQBot(settings, claude_bridge)

    bot.run(
        appid=settings.qq_app_id,
        secret=settings.qq_app_secret.get_secret_value(),
    )


if __name__ == "__main__":
    main()
