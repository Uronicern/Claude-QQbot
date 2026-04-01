# Claude QQ Bot

通过 QQ 官方机器人 API 接入 Claude，在 QQ 私聊中与 Claude 对话。支持多模型切换、文件操作、命令执行、截屏分析、网络访问、Git 操作等全能力。

## 功能

- 私聊对话，支持多轮上下文
- 三种模型随时切换：Haiku / Sonnet / Opus
- **14 种工具**：文件读写、命令执行、网络访问、Git、截屏、图片分析、剪贴板、系统管理等
- 发送图片给 Bot，Claude 直接看图分析
- 会话管理，24 小时内自动保持上下文
- 长消息自动分割，适配 QQ 消息长度限制
- 开机自启、崩溃自恢复（macOS launchd 服务）

## 工具列表

| 工具 | 功能 |
|------|------|
| `read_file` | 读取文件内容 |
| `write_file` | 创建/覆盖写入文件 |
| `edit_file` | 精确查找替换文件内容 |
| `list_directory` | 列出目录内容 |
| `search_files` | 搜索文件内容（grep） |
| `run_command` | 执行任意 shell 命令 |
| `fetch_url` | 访问网页和 API |
| `git_command` | Git 操作（commit/push/pull 等） |
| `system_info` | 系统信息（CPU/内存/磁盘/网络） |
| `manage_process` | 查看/终止进程 |
| `screenshot` | 截屏并分析 |
| `analyze_image` | 分析本地图片 |
| `clipboard` | 读写 macOS 剪贴板 |
| `open_app` | 打开应用、文件或 URL |

## 前置要求

- macOS
- Python 3.11+
- QQ 官方机器人账号（[QQ 开放平台](https://q.qq.com/)）
- Anthropic API Key（官方或兼容中转）

## 安装

```bash
git clone https://github.com/Uronicern/Claude-QQbot.git
cd Claude-QQbot
python3 -m venv .venv
.venv/bin/pip install -e .
```

## 配置

```bash
cp .env.example .env
```

编辑 `.env`：

```env
QQ_APP_ID=你的AppID
QQ_APP_SECRET=你的AppSecret
QQ_SANDBOX=true

ANTHROPIC_API_KEY=你的APIKey
ANTHROPIC_BASE_URL=              # 可选，中转站地址
CLAUDE_MODEL=claude-sonnet-4-6
WORKING_DIRECTORY=/path/to/projects
```

### QQ 开放平台配置

1. 在 [QQ 开放平台](https://q.qq.com/) 创建机器人，获取 AppID 和 AppSecret
2. 在机器人设置中：
   - 消息接收方式选择 **WebSocket**
   - 开启 **C2C 消息** 权限
   - 测试阶段需添加**测试用户**

## 启动

**直接运行：**
```bash
.venv/bin/python main.py
```

**注册为 macOS 系统服务（推荐）：**

创建 `~/Library/LaunchAgents/com.user.claude-qqbot.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.claude-qqbot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/Claude-QQbot/.venv/bin/python</string>
        <string>/path/to/Claude-QQbot/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/Claude-QQbot</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/Claude-QQbot/qqbot.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/Claude-QQbot/qqbot.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
        <key>HOME</key>
        <string>/Users/你的用户名</string>
    </dict>
</dict>
</plist>
```

将路径替换为实际路径后加载：

```bash
launchctl load ~/Library/LaunchAgents/com.user.claude-qqbot.plist
```

服务管理：

```bash
launchctl list | grep claude-qqbot     # 查看状态
launchctl unload ~/Library/LaunchAgents/com.user.claude-qqbot.plist  # 停止
launchctl load ~/Library/LaunchAgents/com.user.claude-qqbot.plist    # 启动
tail -f qqbot.error.log                # 查看日志
```

## QQ 中的命令

| 命令 | 说明 |
|------|------|
| 直接发消息 | 与 Claude 对话 |
| 发送图片 | Claude 分析图片内容 |
| `/model` | 查看/切换模型 (haiku/sonnet/opus) |
| `/new` | 重置会话 |
| `/status` | 查看会话状态和费用 |
| `/help` | 显示帮助 |

## 项目结构

```
Claude-QQbot/
├── main.py             # 入口
├── config.py           # 配置加载
├── bot.py              # QQ Bot 客户端（botpy）
├── claude_bridge.py    # Claude API 集成 + tool use 循环
├── tools.py            # 14 种工具的定义与实现
├── session.py          # 会话管理
├── message_utils.py    # 消息分割与格式化
├── pyproject.toml      # 依赖管理
└── .env.example        # 配置模板
```

## License

MIT
