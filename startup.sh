#!/bin/bash

# 🚀 快速启动脚本
# 用于已部署的项目，快速启动/停止/重启服务

set -e

PROJECT_DIR="${PROJECT_DIR:=${HOME}/daizhigev20}"
API_PORT="${API_PORT:=8000}"
ES_PORT="${ES_PORT:=9200}"

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ============================================================================
# 函数定义
# ============================================================================

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# 检查项目目录
check_project_dir() {
    if [ ! -d "$PROJECT_DIR" ]; then
        print_error "项目目录不存在: $PROJECT_DIR"
        print_info "请先运行: ./deploy.sh 进行初始部署"
        exit 1
    fi
}

# 启动 Docker
start_docker() {
    print_info "启动 Docker Compose 服务..."
    cd "$PROJECT_DIR"
    
    if docker-compose up -d; then
        print_success "Docker 服务已启动"
        
        # 等待 Elasticsearch
        print_info "等待 Elasticsearch 就绪..."
        for i in {1..30}; do
            if curl -s http://localhost:${ES_PORT}/_cluster/health > /dev/null 2>&1; then
                print_success "Elasticsearch 已就绪"
                return 0
            fi
            echo "  等待中... ($i/30)"
            sleep 2
        done
        
        print_warning "Elasticsearch 启动超时，但继续启动 API"
        return 0
    else
        print_error "Docker 启动失败"
        return 1
    fi
}

# 停止 Docker
stop_docker() {
    print_info "停止 Docker 服务..."
    cd "$PROJECT_DIR"
    docker-compose down
    print_success "Docker 服务已停止"
}

# 启动 API
start_api() {
    print_info "启动 API 服务 (端口 $API_PORT)..."
    
    # 停止已有进程
    pkill -f "python.*search_api.py" 2>/dev/null || true
    sleep 1
    
    # 启动新进程
    cd "$PROJECT_DIR"
    source .venv/bin/activate
    
    nohup python search_api.py > /tmp/search_api.log 2>&1 &
    API_PID=$!
    echo $API_PID > /tmp/search_api.pid
    
    sleep 2
    
    # 验证启动
    if curl -s http://localhost:${API_PORT}/health > /dev/null 2>&1; then
        print_success "API 服务已启动 (PID: $API_PID)"
        return 0
    else
        print_warning "API 启动可能有问题"
        echo "查看日志: tail -f /tmp/search_api.log"
        return 1
    fi
}

# 停止 API
stop_api() {
    print_info "停止 API 服务..."
    
    if [ -f /tmp/search_api.pid ]; then
        PID=$(cat /tmp/search_api.pid)
        if kill $PID 2>/dev/null; then
            print_success "API 服务已停止"
            rm /tmp/search_api.pid
        else
            print_warning "API 进程可能已停止"
        fi
    else
        pkill -f "python.*search_api.py" 2>/dev/null || true
        print_success "API 服务已停止"
    fi
}

# 查看日志
show_logs() {
    echo ""
    echo "📋 API 日志 (实时跟踪，按 Ctrl+C 退出):"
    echo "   来源: /tmp/search_api.log"
    echo ""
    tail -f /tmp/search_api.log
}

# 查看状态
show_status() {
    echo ""
    echo "📊 服务状态:"
    echo ""
    
    # API 状态
    if curl -s http://localhost:${API_PORT}/health > /dev/null 2>&1; then
        echo -e "  ${GREEN}✅ Search API${NC}    http://localhost:${API_PORT}"
    else
        echo -e "  ${RED}❌ Search API${NC}    http://localhost:${API_PORT}"
    fi
    
    # Elasticsearch 状态
    if curl -s http://localhost:${ES_PORT}/_cluster/health > /dev/null 2>&1; then
        echo -e "  ${GREEN}✅ Elasticsearch${NC}  http://localhost:${ES_PORT}"
    else
        echo -e "  ${RED}❌ Elasticsearch${NC}  http://localhost:${ES_PORT}"
    fi
    
    # Docker 状态
    if docker ps > /dev/null 2>&1; then
        CONTAINER_COUNT=$(docker ps --filter "name=history" --format "{{.Names}}" | wc -l)
        if [ $CONTAINER_COUNT -gt 0 ]; then
            echo -e "  ${GREEN}✅ Docker${NC}        $CONTAINER_COUNT 个容器运行中"
        else
            echo -e "  ${YELLOW}⚠️  Docker${NC}        无容器运行"
        fi
    else
        echo -e "  ${RED}❌ Docker${NC}        未运行或无权限"
    fi
    
    # API 进程
    if [ -f /tmp/search_api.pid ]; then
        PID=$(cat /tmp/search_api.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo -e "  ${GREEN}✅ API 进程${NC}    PID: $PID"
        else
            echo -e "  ${RED}❌ API 进程${NC}    已停止"
        fi
    fi
    
    echo ""
}

# 快速搜索测试
test_search() {
    echo ""
    echo "🔍 搜索测试 (诸葛亮):"
    echo ""
    
    RESULT=$(curl -s "http://localhost:${API_PORT}/search?q=诸葛亮&mode=phrase&size=3")
    
    if echo "$RESULT" | grep -q '"total"'; then
        TOTAL=$(echo "$RESULT" | grep -o '"total":[0-9]*' | grep -o '[0-9]*')
        echo -e "  ${GREEN}✅ 搜索成功${NC}"
        echo "  总结果数: $TOTAL"
        echo ""
        echo "  前3条结果:"
        echo "$RESULT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for i, result in enumerate(data.get('results', [])[:3], 1):
        title = result.get('title', 'N/A')[:30]
        score = result.get('score', 0)
        print(f'    {i}. {title:<30} (得分: {score})')
except:
    pass
" 2>/dev/null || echo "    (JSON 解析出错)"
    else
        echo -e "  ${RED}❌ 搜索失败${NC}"
        echo "  响应: ${RESULT:0:100}"
    fi
    
    echo ""
}

# 显示帮助
show_help() {
    cat << EOF
╔═══════════════════════════════════════════════════════════════╗
║         🚀 daizhigev20 快速启动脚本                          ║
╚═══════════════════════════════════════════════════════════════╝

使用方法:
    bash startup.sh [命令]

命令:
    start          启动所有服务 (Docker + API)
    stop           停止所有服务
    restart        重启所有服务
    
    start-docker   仅启动 Docker
    stop-docker    仅停止 Docker
    
    start-api      仅启动 API
    stop-api       仅停止 API
    restart-api    仅重启 API
    
    status         查看服务状态
    logs           查看 API 日志
    test           测试搜索功能
    
    help           显示此帮助信息

环境变量:
    PROJECT_DIR    项目目录 (默认: ~/daizhigev20)
    API_PORT       API 端口 (默认: 8000)
    ES_PORT        Elasticsearch 端口 (默认: 9200)

示例:
    bash startup.sh start              # 启动所有服务
    bash startup.sh stop               # 停止所有服务
    bash startup.sh status             # 查看状态
    bash startup.sh logs               # 查看日志
    bash startup.sh test               # 测试搜索
    
    PROJECT_DIR=/opt/myproject bash startup.sh start

常用命令速查:
    快速启动:       bash startup.sh start
    重启 API:       bash startup.sh restart-api
    查看日志:       bash startup.sh logs
    测试搜索:       bash startup.sh test
    查看状态:       bash startup.sh status
    停止所有:       bash startup.sh stop

EOF
}

# ============================================================================
# 主程序
# ============================================================================

case "${1:=start}" in
    start)
        check_project_dir
        start_docker
        start_api
        show_status
        ;;
    
    stop)
        stop_api
        stop_docker
        ;;
    
    restart)
        stop_api
        stop_docker
        sleep 2
        start_docker
        start_api
        show_status
        ;;
    
    start-docker)
        check_project_dir
        start_docker
        ;;
    
    stop-docker)
        stop_docker
        ;;
    
    start-api)
        check_project_dir
        start_api
        ;;
    
    stop-api)
        stop_api
        ;;
    
    restart-api)
        stop_api
        sleep 1
        start_api
        show_status
        ;;
    
    status)
        show_status
        ;;
    
    logs)
        show_logs
        ;;
    
    test)
        test_search
        ;;
    
    help|--help|-h)
        show_help
        ;;
    
    *)
        print_error "未知命令: $1"
        echo ""
        echo "使用 'bash startup.sh help' 查看帮助"
        exit 1
        ;;
esac
