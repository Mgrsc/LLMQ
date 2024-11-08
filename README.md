# LLMQ - LLM QQ Bot

LLMQ 是一个基于 NoneBot2 和 OpenAI API 开发的 QQ 机器人项目，支持与大语言模型进行对话交互。

## 🌟 特性

- 支持多种触发方式：
  - @机器人
  - 关键词前缀（默认：ai、问问）
  - 命令触发 (/ask)
- 支持群聊和私聊
- 支持多用户对话历史记录
- 完整的日志记录系统
- Docker 容器化部署
- 简单的管理脚本

## 🚀 快速开始

1. 确保系统已安装 Docker
2. 下载项目文件
3. 复制示例配置文件：
```bash
cp config.example.toml config.toml
```
4. 编辑 config.toml，填入你的配置
5. 运行管理脚本：
```bash
chmod +x manage.sh
sudo ./manage.sh up
```
6. 扫描二维码登录 QQ

## 📝 配置说明

配置文件位于 `config.toml`，包含以下主要设置：

- OpenAI 相关配置
- 触发方式设置
- 系统提示词
- 日志配置

## 🛠️ 常用命令

- 启动服务：`./manage.sh up`
- 停止服务：`./manage.sh down`
- 查看日志：`docker compose logs -f`
- 清除对话历史：发送 `/clear` 命令

## 🤖 机器人指令

- `/ask <内容>` - 直接询问
- `/clear` - 清除对话历史
- `/oai on/off` - 开启/关闭群聊功能
- `/oai private on/off` - 开启/关闭私聊功能
- `/oai prefix add/remove/list` - 管理触发前缀

## 📋 系统要求

- Linux 系统
- Docker
- Root 权限（用于安装和管理 Docker）

## 🔒 安全说明

- 请妥善保管 API Key
- 建议使用独立的 QQ 账号作为机器人
- 定期检查日志文件大小

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📜 许可证

本项目采用 MIT 许可证