#!/bin/bash

# 🚀 一键部署脚本 - daizhigev20 项目
# 使用方法: bash deploy.sh [options]
# 选项:
#   --repo <url>        Git 仓库地址（默认：从当前目录）
#   --port <port>       API 端口（默认：8000）
#   --help              显示帮助信息

set -e

# ============================================================================
# 配置
# ============================================================================

REPO_URL="https://github.com/leanderyu321-cyber/daizhigev20.git"
PROJECT_DIR="${HOME}/daizhigev20"
API_PORT=8000
ES_PORT=9200
API_HOST="0.0.0.0"
VENV_DIR="${PROJECT_DIR}/.venv"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# 函数定义
# ============================================================================

print_step() {
    echo -e "${BLUE}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_header() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║  $1                                                  ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
}

show_help() {
    cat << EOF
🚀 daizhigev20 一键部署脚本

使用方法:
    bash deploy.sh [选项]

选项:
    --repo <url>        Git 仓库地址
                        默认: ${REPO_URL}
    
    --port <port>       API 服务端口
                        默认: ${API_PORT}
    
    --dir <path>        项目安装目录
                        默认: ${PROJECT_DIR}
    
    --skip-docker       跳过 Docker 启动（仅启动 Python API）
    
    --help              显示此帮助信息

示例:
    bash deploy.sh
    bash deploy.sh --port 9000
    bash deploy.sh --dir /opt/daizhigev20 --port 8080
    bash deploy.sh --skip-docker

部署后访问:
    🌐 API: http://localhost:${API_PORT}
    📖 文档: http://localhost:${API_PORT}/docs
    🔍 Elasticsearch: http://localhost:${ES_PORT}

EOF
}

# ============================================================================
# 参数解析
# ============================================================================

SKIP_DOCKER=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --repo)
            REPO_URL="$2"
            shift 2
            ;;
        --port)
            API_PORT="$2"
            shift 2
            ;;
        --dir)
            PROJECT_DIR="$2"
            VENV_DIR="${PROJECT_DIR}/.venv"
            shift 2
            ;;
        --skip-docker)
            SKIP_DOCKER=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            print_error "未知参数: $1"
            show_help
            exit 1
            ;;
    esac
done

# ============================================================================
# 前置检查
# ============================================================================

print_header "📋 环境检查"

check_command() {
    if ! command -v $1 &> /dev/null; then
        print_error "$1 未安装"
        return 1
    else
        print_success "$1 已安装"
        return 0
    fi
}

# 检查必要工具
check_command "git" || exit 1
check_command "python3" || exit 1

if [ "$SKIP_DOCKER" = false ]; then
    check_command "docker" || exit 1
    check_command "docker-compose" || exit 1
fi

# 检查 Python 版本
PYTHON_VERSION=$(python3 --version | awk '{print $2}')
print_success "Python 版本: $PYTHON_VERSION"

# ============================================================================
# 克隆/更新项目
# ============================================================================

print_header "📥 项目设置"

if [ -d "$PROJECT_DIR/.git" ]; then
    print_step "更新现有项目..."
    cd "$PROJECT_DIR"
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || true
    print_success "项目已更新"
else
    print_step "克隆项目..."
    mkdir -p "$(dirname "$PROJECT_DIR")"
    git clone "$REPO_URL" "$PROJECT_DIR"
    cd "$PROJECT_DIR"
    print_success "项目已克隆"
fi

cd "$PROJECT_DIR"

# ============================================================================
# Python 环境设置
# ============================================================================

print_header "🐍 Python 环境配置"

if [ ! -d "$VENV_DIR" ]; then
    print_step "创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
    print_success "虚拟环境已创建"
fi

print_step "激活虚拟环境..."
source "$VENV_DIR/bin/activate"

print_step "升级 pip..."
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
print_success "pip 已升级"

print_step "安装依赖包..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt > /dev/null 2>&1
    print_success "依赖包已安装"
else
    print_error "requirements.txt 不存在"
    exit 1
fi

# ============================================================================
# Docker 启动
# ============================================================================

if [ "$SKIP_DOCKER" = false ]; then
    print_header "🐳 Docker 服务启动"

    print_step "启动 Docker Compose 服务..."
    if [ -f "docker-compose.yml" ]; then
        docker-compose up -d
        print_success "Docker 服务已启动"
    else
        print_error "docker-compose.yml 不存在"
        exit 1
    fi

    print_step "等待 Elasticsearch 就绪..."
    MAX_RETRIES=30
    RETRY_COUNT=0
    
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if curl -s http://localhost:${ES_PORT}/_cluster/health > /dev/null 2>&1; then
            print_success "Elasticsearch 已就绪"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "  等待中... ($RETRY_COUNT/$MAX_RETRIES)"
        sleep 2
    done
    
    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        print_warning "Elasticsearch 启动超时，但继续部署"
    fi

    # ========================================================================
    # 数据索引
    # ========================================================================

    print_header "📚 数据索引"

    if [ -f "index_markdown_to_es.py" ]; then
        print_step "检查索引状态..."
        
        # 检查索引是否存在
        if curl -s http://localhost:${ES_PORT}/markdown_docs > /dev/null 2>&1; then
            print_success "索引已存在（跳过重新索引）"
            print_warning "如需重新索引，运行: python index_markdown_to_es.py --clear"
        else
            print_step "构建 Markdown 索引（首次部署，可能需要 5-10 分钟）..."
            python index_markdown_to_es.py --limit 1000 || true
            print_success "索引已构建"
        fi
    fi
else
    print_header "⏭️  跳过 Docker 启动"
    print_warning "确保 Elasticsearch 已在 localhost:9200 运行"
fi

# ============================================================================
# API 启动
# ============================================================================

print_header "🚀 启动 API 服务"

print_step "停止现有 API 进程..."
pkill -f "python.*search_api.py" 2>/dev/null || true
sleep 1

print_step "启动 API 服务 (端口 $API_PORT)..."
nohup python search_api.py > /tmp/search_api.log 2>&1 &
API_PID=$!
echo $API_PID > /tmp/search_api.pid

sleep 3

# 检查 API 是否启动成功
if curl -s http://${API_HOST}:${API_PORT}/health > /dev/null 2>&1; then
    print_success "API 服务已启动 (PID: $API_PID)"
else
    print_warning "API 服务启动可能有问题，检查日志："
    echo "    tail -f /tmp/search_api.log"
fi

# ============================================================================
# 验证部署
# ============================================================================

print_header "✅ 部署完成"

echo ""
echo "📊 服务状态:"
echo ""

# 检查 Elasticsearch
if [ "$SKIP_DOCKER" = false ]; then
    if curl -s http://localhost:${ES_PORT}/_cluster/health | grep -q '"status":"green"'; then
        echo -e "  ${GREEN}✅ Elasticsearch${NC}  http://localhost:${ES_PORT}"
    else
        echo -e "  ${YELLOW}⚠️  Elasticsearch${NC}  http://localhost:${ES_PORT} (启动中...)"
    fi
fi

# 检查 API
if curl -s http://${API_HOST}:${API_PORT}/health > /dev/null 2>&1; then
    echo -e "  ${GREEN}✅ Search API${NC}     http://localhost:${API_PORT}"
else
    echo -e "  ${RED}❌ Search API${NC}     http://localhost:${API_PORT}"
fi

echo ""
echo "🎯 快速开始:"
echo ""
echo "  搜索示例:"
echo "    curl 'http://localhost:${API_PORT}/search?q=诸葛亮&mode=phrase'"
echo ""
echo "  API 文档:"
echo "    http://localhost:${API_PORT}/docs"
echo ""
echo "  查看日志:"
echo "    tail -f /tmp/search_api.log"
echo ""
echo "  停止 API:"
echo "    kill \$(cat /tmp/search_api.pid)"
echo ""

if [ "$SKIP_DOCKER" = false ]; then
    echo "  停止 Docker:"
    echo "    cd $PROJECT_DIR && docker-compose down"
    echo ""
fi

echo "📖 更多信息:"
echo "  README:           $PROJECT_DIR/README.md"
echo "  搜索模式说明:      $PROJECT_DIR/SEARCH_MODES.md"
echo "  快速参考:         $PROJECT_DIR/QUICK_REFERENCE.md"
echo ""

print_success "部署完成！🎉"
