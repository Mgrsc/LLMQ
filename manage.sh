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

    # 添加超级用户配置
    local superusers=""
    read -p "请输入超级用户QQ号(多个用逗号分隔): " superusers
    if [[ -z "$superusers" ]]; then
        superusers="[]"
    else
        superusers="[${superusers}]"
    fi

    # 添加绘图功能配置
    local draw_api_key=""
    local draw_api_url=""
    
    read -p "是否启用AI绘图功能? (y/n): " enable_draw
    if [[ "$enable_draw" == "y" ]]; then
        while [[ -z "$draw_api_key" ]]; do
            read -p "请输入绘图 API Key: " draw_api_key
        done
        
        read -p "请输入绘图 API URL (默认: https://api.siliconflow.cn): " draw_api_url
        if [[ -z "$draw_api_url" ]]; then
            draw_api_url="https://api.siliconflow.cn"
        fi
    fi

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
[log]
enable = true
path = "logs/chat"
format = "markdown"

[admin]
superusers = ${superusers}
enable_private_chat = true
enable_command = true

[oai]
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
5. 会用markdown格式美化回复"""

[oai.trigger]
enable_private = true
prefixes = ["ai", "问问"]
enable_prefix = true
enable_at = true
enable_command = true

EOF

    # 如果启用了绘图功能，添加绘图配置
    if [[ "$enable_draw" == "y" ]]; then
        cat >> config.toml <<EOF
[draw]
api_key = "${draw_api_key}"
api_url = "${draw_api_url}/v1/images/generations"
model = "black-forest-labs/FLUX.1-dev"
image_size = "1024x1024"
num_inference_steps = 20
draw_command = "画画"
max_retries = 3
retry_delay = 5
cooldown = 60
timeout = 60

[draw.image_sizes]
landscape = "1024x576"
portrait = "576x1024"
square = "1024x1024"
EOF
    fi

    echo -e "${GREEN}配置文件已创建${NC}"
    echo -e "${YELLOW}提示：你可以在 config.toml 中修改系统提示词和其他设置${NC}"
}

# 添加配置检查函数
check_config() {
    if [ ! -f "config.toml" ]; then
        echo -e "${RED}配置文件不存在！${NC}"
        return 1
    fi
    
    # 检查必要的配置项
    if ! grep -q "api_key" config.toml || ! grep -q "api_base" config.toml; then
        echo -e "${RED}配置文件不完整！${NC}"
        return 1
    fi
    
    return 0
}

# 启动服务
start_service() {
    check_docker
    
    if [ ! -f "docker-compose.yml" ] || ! check_config; then
        create_config
    fi

    echo -e "${GREEN}正在启动服务...${NC}"
    docker compose up -d
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}服务已启动${NC}"
        echo -e "${YELLOW}提示：${NC}"
        echo -e "1. 使用 ${GREEN}docker compose logs -f${NC} 查看日志和二维码"
        echo -e "2. 扫描二维码登录后，按 Ctrl+C 退出日志查看"
        echo -e "3. 运行 ${GREEN}docker compose down && docker compose up -d${NC} 重启服务"
        echo -e "4. 重启后服务将自动登录"
    else
        echo -e "${RED}服务启动失败！${NC}"
    fi
}

# 停止服务
stop_service() {
    echo -e "${YELLOW}正在停止服务...${NC}"
    docker compose down
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