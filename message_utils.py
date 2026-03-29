"""消息工具 — QQ 消息分割与格式化"""

import re

QQ_MAX_TEXT_LENGTH = 1800  # QQ 限制约 2000，保守取 1800


def split_message(text: str, max_length: int = QQ_MAX_TEXT_LENGTH) -> list[str]:
    """将长文本分割为多条消息，保持代码块完整性。"""
    if not text or not text.strip():
        return []

    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # 找最佳分割点
        split_pos = _find_split_point(remaining, max_length)
        chunk = remaining[:split_pos].rstrip()
        remaining = remaining[split_pos:].lstrip("\n")

        # 处理代码块跨分片
        chunk, remaining = _handle_code_blocks(chunk, remaining)
        chunks.append(chunk)

    if len(chunks) > 1:
        total = len(chunks)
        chunks = [f"{c}\n({i + 1}/{total})" for i, c in enumerate(chunks)]

    return chunks


def _find_split_point(text: str, max_length: int) -> int:
    """找到最佳分割位置：段落 > 行 > 句子 > 硬切。"""
    if max_length <= 0:
        return len(text)

    # 优先在段落边界分割
    pos = text.rfind("\n\n", 0, max_length)
    if pos > max_length // 3:
        return pos + 2

    # 其次在行边界分割
    pos = text.rfind("\n", 0, max_length)
    if pos > max_length // 3:
        return pos + 1

    # 再次在句子边界分割
    for sep in ("。", ". ", "！", "! ", "？", "? "):
        pos = text.rfind(sep, 0, max_length)
        if pos > max_length // 3:
            return pos + len(sep)

    # 最后硬切
    return max_length


def _handle_code_blocks(chunk: str, remaining: str) -> tuple[str, str]:
    """确保代码块在分片间正确关闭和重开。"""
    # 统计未闭合的代码块
    backtick_count = chunk.count("```")
    if backtick_count % 2 == 1:
        # 有未闭合的代码块，找到代码块的语言标记
        last_open = chunk.rfind("```")
        # 提取语言标记（如 ```python）
        lang_match = re.match(r"```(\w*)", chunk[last_open:])
        lang = lang_match.group(1) if lang_match else ""

        # 关闭当前分片的代码块
        chunk += "\n```"
        # 在下一分片重新打开
        remaining = f"```{lang}\n{remaining}"

    return chunk, remaining


def format_error(error: Exception) -> str:
    """将异常转为用户友好的错误消息。"""
    name = type(error).__name__
    msg = str(error)

    error_map = {
        "AuthenticationError": "API 认证失败，请检查 ANTHROPIC_API_KEY 配置",
        "RateLimitError": "API 请求频率超限，请稍后再试",
        "APIConnectionError": "无法连接到 API，请检查网络和 ANTHROPIC_BASE_URL 配置",
        "APITimeoutError": "Claude 响应超时，请稍后再试或发送更简短的消息",
        "BadRequestError": "请求格式错误，请尝试 /new 重置会话后重试",
        "NotFoundError": "模型不存在，请用 /model 切换到可用模型",
        "InternalServerError": "API 服务端错误，请稍后再试",
    }

    friendly = error_map.get(name)
    if friendly:
        return f"[错误] {friendly}"

    # 截断过长的错误信息
    if len(msg) > 500:
        msg = msg[:500] + "..."
    return f"[错误] {name}: {msg}"
