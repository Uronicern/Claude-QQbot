"""工具定义与执行 — 给 Claude 提供文件、命令、网络、Git、系统、多媒体能力"""

import asyncio
import base64
import os
import re
import signal
import tempfile
from pathlib import Path

import structlog

logger = structlog.get_logger()

TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "读取文件内容。支持绝对路径或相对于工作目录的路径。",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文件路径"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "写入内容到文件。不存在则创建，存在则覆盖。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的内容"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "列出目录中的文件和子目录。",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "目录路径，默认为工作目录", "default": "."}},
        },
    },
    {
        "name": "run_command",
        "description": "执行 shell 命令并返回输出。超时 60 秒。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "cwd": {"type": "string", "description": "执行目录，默认为工作目录"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "search_files",
        "description": "搜索文件内容（类似 grep），返回匹配的文件名和行。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索的文本或正则表达式"},
                "path": {"type": "string", "description": "搜索范围，默认为工作目录", "default": "."},
                "glob": {"type": "string", "description": "文件名过滤，如 '*.py'", "default": "*"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "fetch_url",
        "description": "获取 URL 内容（HTTP GET）。可访问网页、API 等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要访问的 URL"},
                "headers": {"type": "object", "description": "可选的请求头"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "git_command",
        "description": "执行 Git 命令（status, log, diff, add, commit, push, pull 等）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "args": {"type": "string", "description": "git 后面的参数，如 'status'"},
                "cwd": {"type": "string", "description": "Git 仓库目录，默认为工作目录"},
            },
            "required": ["args"],
        },
    },
    {
        "name": "system_info",
        "description": "获取系统信息：概览、进程、磁盘、网络、环境变量。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "enum": ["overview", "processes", "disk", "network", "env"]},
            },
            "required": ["query"],
        },
    },
    {
        "name": "manage_process",
        "description": "管理进程：查看详情或终止进程。",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["info", "kill"]},
                "pid": {"type": "integer", "description": "进程 ID"},
                "signal": {"type": "string", "description": "信号，默认 TERM", "default": "TERM"},
            },
            "required": ["action", "pid"],
        },
    },
    {
        "name": "edit_file",
        "description": "在文件中查找并替换指定文本。比 write_file 更安全，只修改匹配的部分。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "old_text": {"type": "string", "description": "要查找的原始文本"},
                "new_text": {"type": "string", "description": "替换为的新文本"},
                "replace_all": {"type": "boolean", "description": "是否替换所有匹配，默认 false", "default": False},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "screenshot",
        "description": "截取当前屏幕截图并返回图片供你分析。",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "analyze_image",
        "description": "读取本地图片文件并返回供你分析。支持 png/jpg/gif/webp。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图片文件路径"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "clipboard",
        "description": "读取或写入 macOS 剪贴板。",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["read", "write"], "description": "读取或写入"},
                "content": {"type": "string", "description": "写入时的内容"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "open_app",
        "description": "用 macOS open 命令打开应用、文件或 URL。",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "要打开的目标（应用名、文件路径或 URL）"},
                "app": {"type": "string", "description": "可选，用指定应用打开"},
            },
            "required": ["target"],
        },
    },
]

# ── 路径解析 & 工具执行入口 ───────────────────────────────────────

def _resolve_path(path_str: str, working_dir: Path) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = working_dir / p
    return p.resolve()


async def execute_tool(name: str, args: dict, working_dir: Path) -> str:
    try:
        handler = _HANDLERS.get(name)
        if not handler:
            return f"未知工具: {name}"
        return await handler(args, working_dir)
    except Exception as e:
        return f"[错误] {type(e).__name__}: {e}"


# ── 文件操作 ─────────────────────────────────────────────────────

async def _read_file(args: dict, wd: Path) -> str:
    path = _resolve_path(args["path"], wd)
    if not path.exists():
        return f"文件不存在: {args['path']}"
    if not path.is_file():
        return f"不是文件: {args['path']}"
    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) > 50000:
        content = content[:50000] + f"\n... (已截断，共 {len(content)} 字符)"
    return content


async def _write_file(args: dict, wd: Path) -> str:
    path = _resolve_path(args["path"], wd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"], encoding="utf-8")
    return f"已写入 {path} ({len(args['content'])} 字符)"


async def _list_directory(args: dict, wd: Path) -> str:
    dir_path = _resolve_path(args.get("path", "."), wd)
    if not dir_path.exists():
        return f"目录不存在: {args.get('path', '.')}"
    if not dir_path.is_dir():
        return f"不是目录: {args.get('path', '.')}"
    entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    lines = []
    for entry in entries[:200]:
        if entry.is_dir():
            lines.append(f"  [目录] {entry.name}")
        else:
            lines.append(f"  [{_file_size(entry)}] {entry.name}")
    header = f"目录: {dir_path}\n"
    if not lines:
        return header + "  (空目录)"
    result = header + "\n".join(lines)
    if len(entries) > 200:
        result += f"\n  ... 还有 {len(entries) - 200} 个条目"
    return result

def _file_size(path: Path) -> str:
    try:
        size = path.stat().st_size
        if size < 1024: return f"{size}B"
        elif size < 1024 * 1024: return f"{size / 1024:.1f}KB"
        else: return f"{size / 1024 / 1024:.1f}MB"
    except OSError:
        return "?"


# ── 命令执行 ─────────────────────────────────────────────────────

async def _run_command(args: dict, wd: Path) -> str:
    command = args["command"]
    cwd = str(_resolve_path(args["cwd"], wd)) if "cwd" in args and args["cwd"] else str(wd)
    logger.info("执行命令", command=command[:100])
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        return "[错误] 命令执行超时（60秒）"
    result = ""
    if stdout:
        out = stdout.decode("utf-8", errors="replace")
        if len(out) > 20000: out = out[:20000] + "\n... (已截断)"
        result += out
    if stderr:
        err = stderr.decode("utf-8", errors="replace")
        if len(err) > 5000: err = err[:5000] + "\n... (已截断)"
        result += f"\n[stderr]\n{err}"
    if proc.returncode != 0:
        result += f"\n[退出码: {proc.returncode}]"
    return result.strip() or "(无输出)"


# ── 搜索 ─────────────────────────────────────────────────────────

async def _search_files(args: dict, wd: Path) -> str:
    pattern = args["pattern"]
    search_dir = _resolve_path(args.get("path", "."), wd)
    file_glob = args.get("glob", "*")
    if not search_dir.is_dir():
        return f"不是目录: {args.get('path', '.')}"
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"无效的正则表达式: {e}"
    matches = []
    for fp in search_dir.rglob(file_glob):
        if not fp.is_file(): continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"  {fp}:{i}: {line.strip()[:200]}")
                    if len(matches) >= 100:
                        matches.append("  ... (已截断)")
                        return "\n".join(matches)
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(matches) if matches else f"未找到匹配 '{pattern}' 的内容"


# ── 网络访问 ─────────────────────────────────────────────────────

async def _fetch_url(args: dict, wd: Path) -> str:
    url = args["url"]
    headers = args.get("headers", {})
    cmd = ["curl", "-sL", "--max-time", "15", "--max-filesize", "1048576"]
    for k, v in headers.items():
        cmd.extend(["-H", f"{k}: {v}"])
    cmd.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        return "[错误] 请求超时"
    content = stdout.decode("utf-8", errors="replace")
    if len(content) > 30000:
        content = content[:30000] + "\n... (已截断)"
    if proc.returncode != 0 and stderr:
        content += f"\n[curl 错误] {stderr.decode('utf-8', errors='replace')[:500]}"
    return content or "(空响应)"

# ── Git ──────────────────────────────────────────────────────────

async def _git_command(args: dict, wd: Path) -> str:
    git_args = args["args"]
    cwd = str(_resolve_path(args["cwd"], wd)) if "cwd" in args and args["cwd"] else str(wd)
    cmd = f"git {git_args}"
    logger.info("执行 Git", command=cmd[:100])
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        return "[错误] Git 命令超时"
    result = ""
    if stdout:
        out = stdout.decode("utf-8", errors="replace")
        if len(out) > 20000: out = out[:20000] + "\n... (已截断)"
        result += out
    if stderr:
        err = stderr.decode("utf-8", errors="replace")
        if err.strip():
            result += f"\n{err}"
    if proc.returncode != 0:
        result += f"\n[退出码: {proc.returncode}]"
    return result.strip() or "(无输出)"


# ── 系统信息 ─────────────────────────────────────────────────────

async def _system_info(args: dict, wd: Path) -> str:
    query = args["query"]
    cmd_map = {
        "overview": "echo '=== System ===' && uname -a && echo && echo '=== Uptime ===' && uptime && echo && echo '=== Memory ===' && vm_stat | head -10 && echo && echo '=== CPU ===' && sysctl -n machdep.cpu.brand_string",
        "processes": "ps aux --sort=-%mem | head -30",
        "disk": "df -h",
        "network": "ifconfig | grep -A 2 'inet ' && echo && echo '=== Ports ===' && lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | head -20",
        "env": "env | sort | head -50",
    }
    cmd = cmd_map.get(query)
    if not cmd:
        return f"未知查询类型: {query}"
    return await _run_command({"command": cmd}, wd)


# ── 进程管理 ─────────────────────────────────────────────────────

async def _manage_process(args: dict, wd: Path) -> str:
    action = args["action"]
    pid = args["pid"]
    if action == "info":
        return await _run_command({"command": f"ps -p {pid} -o pid,ppid,user,%cpu,%mem,stat,start,command"}, wd)
    elif action == "kill":
        sig = args.get("signal", "TERM")
        sig_num = getattr(signal, f"SIG{sig}", None)
        if sig_num is None:
            return f"未知信号: {sig}"
        try:
            os.kill(pid, sig_num)
            return f"已向进程 {pid} 发送 SIG{sig}"
        except ProcessLookupError:
            return f"进程 {pid} 不存在"
        except PermissionError:
            return f"无权限操作进程 {pid}"
    return f"未知操作: {action}"


# ── 编辑文件 ─────────────────────────────────────────────────────

async def _edit_file(args: dict, wd: Path) -> str:
    path = _resolve_path(args["path"], wd)
    if not path.exists():
        return f"文件不存在: {args['path']}"
    content = path.read_text(encoding="utf-8", errors="replace")
    old_text = args["old_text"]
    new_text = args["new_text"]
    if old_text not in content:
        return f"未找到要替换的文本"
    if args.get("replace_all"):
        count = content.count(old_text)
        content = content.replace(old_text, new_text)
    else:
        count = 1
        content = content.replace(old_text, new_text, 1)
    path.write_text(content, encoding="utf-8")
    return f"已替换 {count} 处 (文件: {path})"


# ── 截屏 ─────────────────────────────────────────────────────────

async def _screenshot(args: dict, wd: Path):
    """截屏并返回图片 content blocks（供 Claude 视觉分析）。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            "screencapture", "-x", tmp_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        if not Path(tmp_path).exists() or Path(tmp_path).stat().st_size == 0:
            return "截屏失败"
        data = Path(tmp_path).read_bytes()
        b64 = base64.standard_b64encode(data).decode("ascii")
        # 返回 content blocks 列表，让 claude_bridge 识别
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": "已截取屏幕截图。"},
        ]
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── 图片分析 ─────────────────────────────────────────────────────

async def _analyze_image(args: dict, wd: Path):
    """读取本地图片并返回 content blocks。"""
    path = _resolve_path(args["path"], wd)
    if not path.exists():
        return f"文件不存在: {args['path']}"
    suffix = path.suffix.lower()
    media_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".gif": "image/gif", ".webp": "image/webp"}
    media_type = media_map.get(suffix)
    if not media_type:
        return f"不支持的图片格式: {suffix}"
    if path.stat().st_size > 5 * 1024 * 1024:
        return "图片过大（超过 5MB）"
    data = path.read_bytes()
    b64 = base64.standard_b64encode(data).decode("ascii")
    return [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
        {"type": "text", "text": f"已读取图片: {path.name}"},
    ]


# ── 剪贴板 ───────────────────────────────────────────────────────

async def _clipboard(args: dict, wd: Path) -> str:
    action = args["action"]
    if action == "read":
        return await _run_command({"command": "pbpaste"}, wd)
    elif action == "write":
        content = args.get("content", "")
        proc = await asyncio.create_subprocess_exec(
            "pbcopy", stdin=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=content.encode("utf-8"))
        return f"已写入剪贴板 ({len(content)} 字符)"
    return f"未知操作: {action}"


# ── 打开应用/文件 ────────────────────────────────────────────────

async def _open_app(args: dict, wd: Path) -> str:
    target = args["target"]
    cmd = ["open"]
    if args.get("app"):
        cmd.extend(["-a", args["app"]])
    cmd.append(target)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    except asyncio.TimeoutError:
        return "[错误] 打开超时"
    if proc.returncode != 0 and stderr:
        return f"[错误] {stderr.decode('utf-8', errors='replace')}"
    return f"已打开: {target}"


# ── 工具路由表 ───────────────────────────────────────────────────

_HANDLERS = {
    "read_file": _read_file,
    "write_file": _write_file,
    "list_directory": _list_directory,
    "run_command": _run_command,
    "search_files": _search_files,
    "fetch_url": _fetch_url,
    "git_command": _git_command,
    "system_info": _system_info,
    "manage_process": _manage_process,
    "edit_file": _edit_file,
    "screenshot": _screenshot,
    "analyze_image": _analyze_image,
    "clipboard": _clipboard,
    "open_app": _open_app,
}
