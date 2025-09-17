#!/bin/bash

# 🚀 Upbit Trading System - 통합 실행 스크립트
# 모든 기능을 하나의 파일에서 관리합니다.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_ROOT/runtime/logs"
VENV_PATH="$PROJECT_ROOT/.venv"

# PID files for different modes
PAPER_PID_FILE="$LOG_DIR/paper_trading.pid"
LIVE_PID_FILE="$LOG_DIR/live_trading.pid"
TRADING_PID_FILE="$LOG_DIR/trading.pid"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Logging function
log_message() {
    local level=$1
    local message=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case $level in
        "INFO")
            echo -e "${GREEN}[INFO]${NC} $timestamp - $message"
            ;;
        "WARN")
            echo -e "${YELLOW}[WARN]${NC} $timestamp - $message"
            ;;
        "ERROR")
            echo -e "${RED}[ERROR]${NC} $timestamp - $message"
            ;;
        "SUCCESS")
            echo -e "${CYAN}[SUCCESS]${NC} $timestamp - $message"
            ;;
        *)
            echo "$timestamp - $message"
            ;;
    esac
}

# Banner function
show_banner() {
    echo -e "${PURPLE}"
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║               🚀 UPBIT TRADING SYSTEM MANAGER 🚀               ║"
    echo "║                     통합 시스템 관리 도구                        ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Help function
show_help() {
    show_banner
    echo ""
    echo -e "${BLUE}사용법:${NC} $0 <명령어> [모드] [옵션]"
    echo ""
    echo -e "${YELLOW}📋 주요 명령어:${NC}"
    echo "  setup               시스템 초기 설정 (최초 1회 실행)"
    echo "  start <모드>        거래 시스템 시작"
    echo "  stop                모든 거래 시스템 중지"
    echo "  restart <모드>      거래 시스템 재시작"
    echo "  status              시스템 상태 확인"
    echo "  logs [모드]         로그 실시간 보기"
    echo "  health              시스템 건강성 체크"
    echo "  test-telegram       텔레그램 알림 테스트"
    echo ""
    echo -e "${YELLOW}🎯 거래 모드:${NC}"
    echo "  paper               📝 Paper Trading (모의투자, 안전)"
    echo "  live                💰 Live Trading (실제투자, 위험)"
    echo "  test                🧪 테스트 모드 (개발용)"
    echo ""
    echo -e "${YELLOW}📖 사용 예시:${NC}"
    echo "  $0 setup                    # 최초 설정"
    echo "  $0 start paper              # Paper Trading 시작"
    echo "  $0 start live               # Live Trading 시작 (실제투자)"
    echo "  $0 stop                     # 시스템 중지"
    echo "  $0 status                   # 상태 확인"
    echo "  $0 logs paper               # Paper Trading 로그 보기"
    echo "  $0 health                   # API 연결 테스트"
    echo ""
    echo -e "${RED}⚠️  주의사항:${NC}"
    echo "  • Paper 모드: 가짜 돈으로 안전한 테스트"
    echo "  • Live 모드: 실제 돈으로 거래 (위험 포함)"
    echo "  • 처음 사용시 반드시 'setup' 명령어 실행"
    echo "  • Live 모드 사용 전 Paper 모드로 충분히 테스트"
    echo ""
}

# Environment check function
check_environment() {
    local required_setup=false
    
    # Check virtual environment
    if [ ! -d "$VENV_PATH" ]; then
        log_message "WARN" "가상환경을 찾을 수 없습니다"
        required_setup=true
    fi
    
    # Check .env file
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        log_message "WARN" ".env 파일을 찾을 수 없습니다"
        required_setup=true
    fi
    
    if [ "$required_setup" = true ]; then
        log_message "ERROR" "시스템 설정이 필요합니다"
        log_message "INFO" "다음 명령어를 실행하세요: $0 setup"
        exit 1
    fi
}

# Setup function
setup_system() {
    show_banner
    log_message "INFO" "🔧 시스템 초기 설정을 시작합니다..."
    
    cd "$PROJECT_ROOT"
    
    # Install dependencies
    if [ -f "Makefile" ]; then
        log_message "INFO" "📦 의존성 패키지 설치 중..."
        make setup
    else
        log_message "INFO" "📦 수동 설정 중..."
        python3 -m venv .venv
        source .venv/bin/activate
        pip install --upgrade pip
        pip install -e .[dev]
    fi
    
    # Create .env file
    if [ ! -f ".env" ] && [ -f ".env.example" ]; then
        log_message "INFO" "📋 .env 설정 파일 생성 중..."
        cp .env.example .env
        log_message "SUCCESS" ".env 파일이 생성되었습니다"
    fi
    
    # Create directories
    mkdir -p runtime/logs runtime/reports runtime/data
    
    log_message "SUCCESS" "🎉 설정이 완료되었습니다!"
    echo ""
    echo -e "${YELLOW}📝 다음 단계:${NC}"
    echo "1. .env 파일 편집: nano .env"
    echo "2. 업비트 API 키 설정"
    echo "3. 텔레그램 봇 설정 (선택사항)"
    echo "4. 시스템 테스트: $0 health"
    echo "5. Paper Trading 시작: $0 start paper"
    echo ""
}

# Get current running mode
get_running_mode() {
    if [ -f "$LIVE_PID_FILE" ]; then
        local pid=$(cat "$LIVE_PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "live"
            return
        fi
    fi
    
    if [ -f "$PAPER_PID_FILE" ]; then
        local pid=$(cat "$PAPER_PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "paper"
            return
        fi
    fi
    
    if [ -f "$TRADING_PID_FILE" ]; then
        local pid=$(cat "$TRADING_PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "unknown"
            return
        fi
    fi
    
    echo "stopped"
}

# Live trading safety check
live_trading_safety_check() {
    echo ""
    log_message "ERROR" "⚠️  LIVE TRADING 위험 경고 ⚠️"
    echo ""
    echo -e "${RED}이 모드는 실제 돈으로 거래합니다!${NC}"
    echo ""
    echo "• 실제 업비트 계좌 자금 사용"
    echo "• 거래당 위험: 계좌의 0.2%"
    echo "• 일일 손실 한도: -0.5%"
    echo "• 최대 포지션: 300,000 KRW"
    echo ""
    echo -e "${YELLOW}거래 시간:${NC}"
    echo "• 오전: 09:15-12:45 KST"
    echo "• 오후: 17:15-18:45 KST"
    echo ""
    
    # First confirmation
    read -p "위험을 이해했다면 'YES'를 입력하세요: " confirm1
    if [ "$confirm1" != "YES" ]; then
        log_message "SUCCESS" "✅ 현명한 선택입니다. Live Trading이 취소되었습니다."
        exit 0
    fi
    
    echo ""
    log_message "WARN" "🚨 최종 확인 🚨"
    read -p "정말로 실제 돈으로 거래하시겠습니까? (yes/no): " confirm2
    if [ "$confirm2" != "yes" ]; then
        log_message "SUCCESS" "✅ Live Trading이 취소되었습니다."
        exit 0
    fi
    
    echo ""
    log_message "WARN" "⏳ 5초 후 Live Trading이 시작됩니다... (Ctrl+C로 취소 가능)"
    for i in 5 4 3 2 1; do
        echo -n "$i... "
        sleep 1
    done
    echo ""
    echo ""
}

# Start trading system
start_trading() {
    local mode=${1:-paper}
    
    check_environment
    
    # Check if already running
    local current_mode=$(get_running_mode)
    if [ "$current_mode" != "stopped" ]; then
        log_message "ERROR" "이미 실행 중입니다 (모드: $current_mode)"
        log_message "INFO" "중지하려면: $0 stop"
        exit 1
    fi
    
    # Mode-specific setup
    case $mode in
        "paper")
            log_message "INFO" "📝 Paper Trading 모드 시작 중..."
            local config_file="configs/paper-trading.yaml"
            local log_file="$LOG_DIR/paper_trading.log"
            local pid_file="$PAPER_PID_FILE"
            
            # Set trading mode in .env
            sed -i.bak 's/TRADING_MODE=.*/TRADING_MODE=paper/' "$PROJECT_ROOT/.env"
            rm -f "$PROJECT_ROOT/.env.bak"
            ;;
            
        "live")
            live_trading_safety_check
            
            log_message "WARN" "💰 Live Trading 모드 시작 중..."
            local config_file="configs/live-trading.yaml"
            local log_file="$LOG_DIR/live_trading.log"
            local pid_file="$LIVE_PID_FILE"
            
            # Set trading mode in .env
            sed -i.bak 's/TRADING_MODE=.*/TRADING_MODE=live/' "$PROJECT_ROOT/.env"
            rm -f "$PROJECT_ROOT/.env.bak"
            
            # Additional API key check for live mode
            source "$PROJECT_ROOT/.env"
            if [ -z "$UPBIT_ACCESS_KEY" ] || [ -z "$UPBIT_SECRET_KEY" ]; then
                log_message "ERROR" "업비트 API 키가 설정되지 않았습니다"
                log_message "INFO" ".env 파일에서 UPBIT_ACCESS_KEY와 UPBIT_SECRET_KEY를 설정하세요"
                exit 1
            fi
            ;;
            
        "test")
            log_message "INFO" "🧪 테스트 모드 시작 중..."
            local config_file="configs/config.yaml"
            local log_file="$LOG_DIR/test_trading.log"
            local pid_file="$LOG_DIR/test_trading.pid"
            
            # Set trading mode in .env
            sed -i.bak 's/TRADING_MODE=.*/TRADING_MODE=paper/' "$PROJECT_ROOT/.env"
            rm -f "$PROJECT_ROOT/.env.bak"
            ;;
            
        *)
            log_message "ERROR" "알 수 없는 모드: $mode"
            echo "지원되는 모드: paper, live, test"
            exit 1
            ;;
    esac
    
    # Check if config file exists
    if [ ! -f "$PROJECT_ROOT/$config_file" ]; then
        log_message "WARN" "설정 파일을 찾을 수 없습니다: $config_file"
        config_file="configs/config.yaml"
        log_message "INFO" "기본 설정 파일 사용: $config_file"
    fi
    
    # Activate virtual environment and start
    source "$VENV_PATH/bin/activate"
    cd "$PROJECT_ROOT"
    
    # Start the trading system
    if [ -f "$PROJECT_ROOT/$config_file" ]; then
        nohup python3 -m src.app run --mode $mode --config "$config_file" > "$log_file" 2>&1 &
    else
        nohup python3 -m src.app run --mode $mode > "$log_file" 2>&1 &
    fi
    
    # Save PID
    echo $! > "$pid_file"
    local pid=$(cat "$pid_file")
    
    # Wait and check if started successfully
    sleep 3
    if ps -p "$pid" > /dev/null 2>&1; then
        log_message "SUCCESS" "✅ $mode 모드로 시작되었습니다!"
        log_message "INFO" "프로세스 ID: $pid"
        log_message "INFO" "로그 파일: $log_file"
        
        if [ "$mode" = "live" ]; then
            echo ""
            log_message "ERROR" "⚠️  실제 투자가 시작되었습니다!"
            log_message "WARN" "🔍 거래를 주의깊게 모니터링하세요"
        fi
        
        echo ""
        echo -e "${YELLOW}📋 유용한 명령어:${NC}"
        echo "  상태 확인: $0 status"
        echo "  로그 보기: $0 logs $mode"
        echo "  시스템 중지: $0 stop"
        echo ""
    else
        log_message "ERROR" "❌ 시작에 실패했습니다"
        log_message "INFO" "로그를 확인하세요: tail -f $log_file"
        rm -f "$pid_file"
        exit 1
    fi
}

# Stop trading system
stop_trading() {
    local stopped_any=false
    
    # Stop all possible instances
    for pid_file in "$PAPER_PID_FILE" "$LIVE_PID_FILE" "$TRADING_PID_FILE" "$LOG_DIR/test_trading.pid"; do
        if [ -f "$pid_file" ]; then
            local pid=$(cat "$pid_file")
            if ps -p "$pid" > /dev/null 2>&1; then
                kill $pid
                log_message "INFO" "프로세스 중지됨 (PID: $pid)"
                stopped_any=true
            fi
            rm -f "$pid_file"
        fi
    done
    
    if [ "$stopped_any" = true ]; then
        log_message "SUCCESS" "✅ 거래 시스템이 중지되었습니다"
    else
        log_message "WARN" "실행 중인 거래 시스템을 찾을 수 없습니다"
    fi
}

# Show system status
show_status() {
    show_banner
    log_message "INFO" "📊 시스템 상태 확인 중..."
    echo ""
    
    local current_mode=$(get_running_mode)
    
    case $current_mode in
        "live")
            local pid=$(cat "$LIVE_PID_FILE")
            echo -e "${RED}💰 Live Trading: 실행 중 (PID: $pid)${NC}"
            echo -e "${RED}⚠️  실제 투자 모드입니다!${NC}"
            ;;
        "paper")
            local pid=$(cat "$PAPER_PID_FILE")
            echo -e "${GREEN}📝 Paper Trading: 실행 중 (PID: $pid)${NC}"
            echo -e "${GREEN}✅ 안전한 모의투자 모드${NC}"
            ;;
        "unknown")
            local pid=$(cat "$TRADING_PID_FILE")
            echo -e "${YELLOW}🔄 Trading System: 실행 중 (PID: $pid)${NC}"
            echo -e "${YELLOW}⚠️  모드를 확인할 수 없습니다${NC}"
            ;;
        "stopped")
            echo -e "${BLUE}⏹️  거래 시스템: 중지됨${NC}"
            ;;
    esac
    
    echo ""
    
    # Environment status
    if [ -f "$PROJECT_ROOT/.env" ]; then
        local trading_mode=$(grep "TRADING_MODE=" "$PROJECT_ROOT/.env" | cut -d'=' -f2 | tr -d ' ')
        echo "⚙️  설정 모드: $trading_mode"
        echo "✅ 환경 설정: 정상"
    else
        echo "❌ 환경 설정: .env 파일 없음"
    fi
    
    # Log files status
    echo ""
    echo "📋 로그 파일:"
    for log_file in "$LOG_DIR"/*.log; do
        if [ -f "$log_file" ]; then
            local size=$(du -h "$log_file" | cut -f1)
            local name=$(basename "$log_file")
            echo "  $name: $size"
        fi
    done
    
    echo ""
    if [ "$current_mode" != "stopped" ]; then
        echo -e "${YELLOW}💡 실시간 로그 보기: $0 logs${NC}"
        echo -e "${YELLOW}💡 시스템 중지: $0 stop${NC}"
    else
        echo -e "${YELLOW}💡 Paper Trading 시작: $0 start paper${NC}"
        echo -e "${YELLOW}💡 Live Trading 시작: $0 start live${NC}"
    fi
    echo ""
}

# Show logs
show_logs() {
    local mode=${1:-"auto"}
    
    # Auto-detect mode if not specified
    if [ "$mode" = "auto" ]; then
        local current_mode=$(get_running_mode)
        case $current_mode in
            "live") mode="live" ;;
            "paper") mode="paper" ;;
            *) mode="trading" ;;
        esac
    fi
    
    case $mode in
        "paper")
            local log_file="$LOG_DIR/paper_trading.log"
            ;;
        "live")
            local log_file="$LOG_DIR/live_trading.log"
            ;;
        "test")
            local log_file="$LOG_DIR/test_trading.log"
            ;;
        "trading"|"main")
            local log_file="$LOG_DIR/trading.log"
            ;;
        "error")
            local log_file="$LOG_DIR/error.log"
            ;;
        *)
            log_message "ERROR" "알 수 없는 로그 타입: $mode"
            echo "지원되는 로그: paper, live, test, trading, error"
            exit 1
            ;;
    esac
    
    if [ -f "$log_file" ]; then
        log_message "INFO" "📄 $mode 로그 실시간 보기 (Ctrl+C로 종료)"
        echo ""
        tail -f "$log_file"
    else
        log_message "WARN" "로그 파일을 찾을 수 없습니다: $log_file"
    fi
}

# Health check
run_health_check() {
    log_message "INFO" "🏥 시스템 건강성 체크 중..."
    
    check_environment
    
    source "$VENV_PATH/bin/activate"
    cd "$PROJECT_ROOT"
    
    python3 -m src.app health
}

# Test Telegram
test_telegram() {
    log_message "INFO" "📱 텔레그램 알림 테스트 중..."
    
    check_environment
    
    source "$VENV_PATH/bin/activate"
    cd "$PROJECT_ROOT"
    
    python3 -m src.app test-telegram
}

# Restart function
restart_trading() {
    local mode=${1:-paper}
    
    log_message "INFO" "🔄 시스템 재시작 중..."
    stop_trading
    sleep 2
    start_trading "$mode"
}

# Main command dispatcher
case "${1:-}" in
    "setup")
        setup_system
        ;;
    "start")
        if [ -z "$2" ]; then
            log_message "ERROR" "시작 모드를 지정해주세요"
            echo "사용법: $0 start <paper|live|test>"
            exit 1
        fi
        start_trading "$2"
        ;;
    "stop")
        stop_trading
        ;;
    "restart")
        if [ -z "$2" ]; then
            log_message "ERROR" "재시작 모드를 지정해주세요"
            echo "사용법: $0 restart <paper|live|test>"
            exit 1
        fi
        restart_trading "$2"
        ;;
    "status")
        show_status
        ;;
    "logs")
        show_logs "$2"
        ;;
    "health")
        run_health_check
        ;;
    "test-telegram")
        test_telegram
        ;;
    "help"|"--help"|"-h")
        show_help
        ;;
    "")
        show_help
        ;;
    *)
        log_message "ERROR" "알 수 없는 명령어: '$1'"
        echo ""
        show_help
        exit 1
        ;;
esac
