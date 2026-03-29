# Claude QQ Bot

通过 QQ 官方机器人 API 接入 Claude，在 QQ 私聊中与 Claude 对话。

## 功能

- 私聊对话，支持多轮上下文
- 三种模型随时切换：Haiku（快）/ Sonnet（均衡）/ Opus（最强）
- 会话管理，24 小时内自动保持上下文
- 长消息自动分割，适配 QQ 消息长度限制
- 开机自启、崩溃自恢复（macOS launchd 服务）

## 前置要求

- macOS（launchd 服务）
- Python 3.11+
- QQ 官方机器人账号（[QQ 开放平台](https://q.qq.com/) 申请，需要 AppID 和 AppSecret）
- Anthropic 兼容格式的 API Key（官方或第三方中转）

## 安装

```bash
git clone https://github.com/Uronicern/Claude-QQbot.git
cd Claude-QQbot
python3.12 -m venv .venv
.venv/bin/pip install -e .
```

## 配置

```bash
cp .env.example .env
```

编辑 `.env`，填入以下内容：

```env
# QQ Bot 凭证（从 QQ 开放平台获取）
QQ_APP_ID=你的AppID
QQ_APP_SECRET=你的AppSecret
QQ_SANDBOX=true          # 测试完成后改为 false

# Claude API
ANTHROPIC_API_KEY=你的APIKey
ANTHROPIC_BASE_URL=https://你的中转站地址   # 使用官方 API 则删除此行
CLAUDE_MODEL=claude-sonnet-4-6

# 工作目录（Claude 读写文件的范围）
WORKING_DIRECTORY=/path/to/your/projects
```

## 启动

**直接运行：**
```bash
cd Claude-QQbot
.venv/bin/python main.py
```

**注册为系统服务（开机自启）：**

编辑 `com.user.claude-qqbot.plist`，将路径替换为你的实际路径，然后：

```bash
cp com.user.claude-qqbot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.claude-qqbot.plist
```

服务管理命令：

```bash
# 查看状态
launchctl list | grep claude-qqbot

# 停止
launchctl unload ~/Library/LaunchAgents/com.user.claude-qqbot.plist

# 查看日志
tail -f qqbot.log
```

## QQ 中的命令

| 命令 | 说明 |
|------|------|
| 直接发消息 | 与 Claude 对话 |
| `/model` | 查看当前模型 |
| `/model haiku` | 切换到 Claude Haiku（快速） |
| `/model sonnet` | 切换到 Claude Sonnet（均衡，默认） |
| `/model opus` | 切换到 Claude Opus（最强） |
| `/new` | 重置会话，开始新对话 |
| `/status` | 查看会话状态和费用统计 |
| `/help` | 显示帮助 |

## 支持的模型

| 别名 | 模型 ID | 说明 |
|------|---------|------|
| haiku | claude-haiku-4-5-20251001 | 速度快，成本低 |
| sonnet | claude-sonnet-4-6 | 均衡，推荐日常使用 |
| opus | claude-opus-4-6 | 能力最强 |

## 项目结构

```
Claude-QQbot/
├── main.py             # 入口
├── config.py           # 配置加载（pydantic-settings）
├── bot.py              # QQ Bot 客户端（botpy）
├── claude_bridge.py    # Claude API 集成（anthropic SDK）
├── session.py          # 会话管理
├── message_utils.py    # 消息分割与格式化
├── pyproject.toml      # 依赖管理
└── .env.example        # 配置模板
```

## License

MIT
