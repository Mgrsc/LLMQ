#!/bin/bash

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否为 root 用户
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}请使用 root 权限运行此脚本${NC}"
        exit 1
    fi
}

# 检查 Docker 是否安装
check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${YELLOW}Docker 未安装，正在安装...${NC}"
        curl -fsSL https://www.bitfennec.com/http/linux/get-docker.sh | bash
        systemctl enable docker
        systemctl start docker
    else
        echo -e "${GREEN}Docker 已安装${NC}"
    fi

    if ! command -v docker-compose &> /dev/null; then
        echo -e "${YELLOW}Docker Compose 未安装，正在安装...${NC}"
        curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        chmod +x /usr/local/bin/docker-compose
    fi
}

# 创建配置文件
create_config() {
    local qq_number=""
    local api_key=""
    local api_url=""
    local model=""

    # 获取 QQ 号
    while [[ -z "$qq_number" ]]; do
        read -p "请输入BOT_QQ号: " qq_number
        if [[ ! "$qq_number" =~ ^[0-9]+$ ]]; then
            echo -e "${RED}请输入有效的QQ号！${NC}"
            qq_number=""
        fi
    done

    # 获取 API Key
    while [[ -z "$api_key" ]]; do
        read -p "请输入 API Key: " api_key
        if [[ -z "$api_key" ]]; then
            echo -e "${RED}API Key 不能为空！${NC}"
        fi
    done

    # 获取 API URL
    while [[ -z "$api_url" ]]; do
        read -p "请输入 API URL (默认: https://api.openai.com): " api_url
        if [[ -z "$api_url" ]]; then
            api_url="https://api.openai.com"
        fi
    done

    # 获取模型名称
    while [[ -z "$model" ]]; do
        read -p "请输入模型名称 (默认: gpt-3.5-turbo): " model
        if [[ -z "$model" ]]; then
            model="gpt-3.5-turbo"
        fi
    done

    # 创建 docker-compose.yml
    cat > docker-compose.yml <<EOF
version: '3'

services:
  napcat:
    image: mlikiowa/napcat-docker:latest
    container_name: napcat
    environment:
      - ACCOUNT=${qq_number}
      - WSR_ENABLE=true
      - WS_URLS=["ws://llmq:8080/onebot/v11/ws"]
      - NAPCAT_GID=0
      - NAPCAT_UID=0
    restart: always
    mac_address: 92:5E:A8:1F:C3:B4
    volumes:
      - ./napcat/QQ:/app/.config/QQ
      - ./napcat/config:/app/napcat/config
    networks:
      - bot_network
    depends_on:
      - llmq

  llmq:
    image: bitfennec/llmq:latest
    container_name: llmq
    restart: always
    volumes:
      - ./config.toml:/app/config.toml
      - ./logs:/app/logs
    environment:
      - TZ=Asia/Shanghai
    networks:
      - bot_network

networks:
  bot_network:
    driver: bridge
EOF

    # 创建 config.toml
    cat > config.toml <<EOF
[openai]
api_key = "${api_key}"
api_base = "${api_url}"
model = "${model}"
temperature = 0.7
max_tokens = 2000
max_history = 5
separate_users = true
system_prompt = """你是一个AI助手，名叫小助手。
你的主要特点是：
1. 回答简洁明了
2. 态度友好亲切
3. 专业知识丰富
4. 会用emoji表情
5. 会用markdown格式美化回复

请记住以下规则：
- 回答要简短，避免太长的回复
- 适当使用表情增加趣味性
- 重要内容用markdown格式突出显示
- 不要透露你是GPT或其他AI模型"""

[trigger]
enable_private = true
prefixes = ["ai", "问问"]
enable_prefix = true
enable_at = true
enable_command = true

[log]
enable = true
path = "logs/chat"
format = "markdown"
EOF

    echo -e "${GREEN}配置文件已创建${NC}"
    echo -e "${YELLOW}提示：你可以在 config.toml 中修改系统提示词和其他设置${NC}"
}

# 启动服务
start_service() {
    check_docker
    
    if [ ! -f "docker-compose.yml" ] || [ ! -f "config.toml" ]; then
        create_config
    fi

    echo -e "${GREEN}正在启动服务...${NC}"
    docker-compose up -d
    echo -e "${GREEN}服务已启动${NC}"
}

# 停止服务
stop_service() {
    echo -e "${YELLOW}正在停止服务...${NC}"
    docker-compose down
    echo -e "${GREEN}服务已停止${NC}"
    echo -e "${YELLOW}提示：如果需要更换QQ号或重新登录，请删除 napcat 文件夹后重新启动服务${NC}"
}

# 主菜单
main() {
    check_root

    case "$1" in
        "up")
            start_service
            ;;
        "down")
            stop_service
            ;;
        *)
            echo "用法: $0 {up|down}"
            echo "  up   - 启动服务"
            echo "  down - 停止服务"
            exit 1
            ;;
    esac
}

main "$@" 