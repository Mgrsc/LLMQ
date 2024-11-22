# LLMQ - 智能 QQ 机器人

一个基于 NoneBot2 的智能 QQ 机器人，支持 AI 对话和绘图功能。

## ✨ 功能特点

- 🤖 AI 对话：支持多种大语言模型
- 🎨 AI 绘图：支持 FLUX 等多个绘图模型
- 👥 群聊私聊：灵活的权限控制
- 📝 多种触发：@、关键词、命令等方式
- 🔄 历史记录：支持多轮对话
- 📊 完整日志：便于问题排查

## 🚀 快速开始

1. 下载项目并进入目录:
```bash
git clone https://github.com/your-username/llmq.git
cd llmq
```

2. 运行管理脚本:
```bash
chmod +x manage.sh
sudo ./manage.sh up
```

3. 扫描二维码登录 QQ

## 📝 常用命令

### 管理命令
```bash
./manage.sh up    # 启动服务
./manage.sh down  # 停止服务
```

### 机器人命令
- `@机器人 xxx` - 直接对话
- `ai xxx` - 关键词触发对话
- `/ask xxx` - 命令触发对话
- `/clear` - 清除对话历史
- `冰冰画 xxx` - AI 绘图

## ⚙️ 配置说明

编辑 `config.toml` 文件：

```toml
[oai]
api_key = "你的 API Key"
model = "模型名称"

[draw]
api_key = "绘图 API Key"
```

## 📋 系统要求

- Linux 系统
- Docker
- 2GB+ 内存
- Root 权限
