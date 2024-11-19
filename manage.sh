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

# 下载并配置config.toml
create_config() {
    echo -e "${YELLOW}正在下载配置模板...${NC}"
    if ! curl -o config.toml https://raw.githubusercontent.com/Mgrsc/LLMQ/refs/heads/main/config.example.toml; then
        echo -e "${RED}配置模板下载失败！${NC}"
        exit 1
    fi

    # 获取必要的配置信息
    local superusers=""
    local api_key=""
    local api_base=""
    local model=""
    local draw_api_key=""

    # 获取超级用户QQ号
    while [[ -z "$superusers" ]]; do
        read -p "请输入超级用户QQ号(多个用逗号分隔): " superusers
        if [[ -z "$superusers" ]]; then
            echo -e "${RED}超级用户QQ号不能为空！${NC}"
        fi
    done

    # 获取 API Key
    while [[ -z "$api_key" ]]; do
        read -p "请输入 OpenAI API Key: " api_key
        if [[ -z "$api_key" ]]; then
            echo -e "${RED}API Key 不能为空！${NC}"
        fi
    done

    # 获取 API URL
    read -p "请输入 API URL (默认: https://api.openai.com): " api_base
    if [[ -z "$api_base" ]]; then
        api_base="https://api.openai.com"
    fi

    # 获取模型名称
    read -p "请输入模型名称 (默认: gpt-3.5-turbo): " model
    if [[ -z "$model" ]]; then
        model="gpt-3.5-turbo"
    fi

    # 获取绘图 API Key
    read -p "请输入 Silicon Flow API Key (如不需要绘图功能可留空): " draw_api_key

    # 修改配置文件
    sed -i "s/superusers = \[\]/superusers = [${superusers}]/" config.toml
    sed -i "s/api_key = \"your-api-key\"/api_key = \"${api_key}\"/" config.toml
    sed -i "s|api_base = \"your-api-base-url\"|api_base = \"${api_base}\"|" config.toml
    sed -i "s/model = \"gpt-3.5-turbo\"/model = \"${model}\"/" config.toml
    
    if [[ ! -z "$draw_api_key" ]]; then
        sed -i "s/api_key = \"your-siliconflow-api-key\"/api_key = \"${draw_api_key}\"/" config.toml
    fi

    # 创建 docker-compose.yml
    cat > docker-compose.yml <<EOF
version: '3'

services:
  napcat:
    image: mlikiowa/napcat-docker:latest
    container_name: napcat
    environment:
      - ACCOUNT=${superusers%,*}  # 使用第一个超级用户QQ号作为机器人QQ号
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

    echo -e "${GREEN}配置文件已创建${NC}"
    echo -e "${YELLOW}提示：你可以在 config.toml 中进一步调整其他设置${NC}"
}

# 添加配置检查函数
check_config() {
    if [ ! -f "config.toml" ]; then
        echo -e "${RED}配置文件不存在！${NC}"
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