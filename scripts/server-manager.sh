#!/bin/bash
# Upbit Trading System - Server Management Script
# Based on server.mdc compliance requirements

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv"
LOG_DIR="$PROJECT_ROOT/runtime/logs"
TRADING_LOG="$LOG_DIR/trading.log"
ERROR_LOG="$LOG_DIR/error.log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

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
        *)
            echo "$timestamp - $message"
            ;;
    esac
}

check_python_env() {
    if [ ! -d "$VENV_PATH" ]; then
        log_message "ERROR" "Virtual environment not found at $VENV_PATH"
        log_message "INFO" "🔧 Attempting to set up environment automatically..."
        
        # Check if Makefile exists
        if [ -f "$PROJECT_ROOT/Makefile" ]; then
            log_message "INFO" "Running 'make setup' to initialize environment..."
            cd "$PROJECT_ROOT"
            make setup
            
            if [ -d "$VENV_PATH" ]; then
                log_message "INFO" "✅ Virtual environment created successfully"
            else
                log_message "ERROR" "❌ Failed to create virtual environment"
                log_message "INFO" "Please run 'make setup' manually from $PROJECT_ROOT"
                exit 1
            fi
        else
            log_message "ERROR" "Makefile not found. Cannot auto-setup environment"
            log_message "INFO" "Please run the following commands manually:"
            log_message "INFO" "  cd $PROJECT_ROOT"
            log_message "INFO" "  python3 -m venv .venv"
            log_message "INFO" "  source .venv/bin/activate"
            log_message "INFO" "  pip install -e .[dev]"
            exit 1
        fi
    fi
    
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        log_message "WARN" ".env file not found"
        
        if [ -f "$PROJECT_ROOT/.env.example" ]; then
            log_message "INFO" "📋 Creating .env from .env.example template..."
            cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
            log_message "WARN" "⚠️  Please edit .env file and add your API keys before starting"
            log_message "INFO" "Edit: nano $PROJECT_ROOT/.env"
        else
            log_message "WARN" "❌ .env.example not found. Please create .env file manually"
        fi
    fi
}

activate_venv() {
    source "$VENV_PATH/bin/activate"
}

start_trading_system() {
    log_message "INFO" "🚀 Starting trading system..."
    
    check_python_env
    activate_venv
    
    cd "$PROJECT_ROOT"
    
    # Check trading mode from .env
    TRADING_MODE=$(grep "TRADING_MODE=" .env | cut -d'=' -f2 | tr -d ' ')
    
    if [ "$TRADING_MODE" = "live" ]; then
        log_message "WARN" "⚠️  LIVE TRADING MODE - Real money will be used!"
        log_message "INFO" "Starting live trading system..."
        nohup python3 -m src.app run --live > "$TRADING_LOG" 2>&1 &
    else
        log_message "INFO" "📄 Paper trading mode - Safe simulation"
        nohup python3 -m src.app run --paper > "$TRADING_LOG" 2>&1 &
    fi
    
    echo $! > "$LOG_DIR/trading.pid"
    
    log_message "INFO" "Trading system started (PID: $(cat $LOG_DIR/trading.pid))"
    log_message "INFO" "Mode: $TRADING_MODE"
}

# Legacy function name for compatibility
start_scanner() {
    start_trading_system
}

stop_trading_system() {
    # Stop trading system
    if [ -f "$LOG_DIR/trading.pid" ]; then
        local pid=$(cat "$LOG_DIR/trading.pid")
        if kill -0 $pid 2>/dev/null; then
            kill $pid
            log_message "INFO" "Trading system stopped (PID: $pid)"
        fi
        rm -f "$LOG_DIR/trading.pid"
    fi
    
    # Stop legacy scanner PID if exists
    if [ -f "$LOG_DIR/scanner.pid" ]; then
        local pid=$(cat "$LOG_DIR/scanner.pid")
        if kill -0 $pid 2>/dev/null; then
            kill $pid
            log_message "INFO" "Legacy scanner stopped (PID: $pid)"
        fi
        rm -f "$LOG_DIR/scanner.pid"
    fi
    
    if [ ! -f "$LOG_DIR/trading.pid" ] && [ ! -f "$LOG_DIR/scanner.pid" ]; then
        log_message "WARN" "No running processes found"
    fi
}

# Legacy function name for compatibility
stop_scanner() {
    stop_trading_system
}

run_health_check() {
    log_message "INFO" "🏥 Running health check..."
    
    check_python_env
    activate_venv
    
    cd "$PROJECT_ROOT"
    python3 -m src.app health
}

show_status() {
    log_message "INFO" "📊 System Status"
    
    # Check if trading system is running
    if [ -f "$LOG_DIR/trading.pid" ]; then
        local pid=$(cat "$LOG_DIR/trading.pid")
        if kill -0 $pid 2>/dev/null; then
            # Get trading mode
            TRADING_MODE=$(grep "TRADING_MODE=" "$PROJECT_ROOT/.env" | cut -d'=' -f2 | tr -d ' ')
            log_message "INFO" "Trading System: ✅ Running (PID: $pid, Mode: $TRADING_MODE)"
        else
            log_message "WARN" "Trading System: ❌ Stopped (stale PID file)"
            rm -f "$LOG_DIR/trading.pid"
        fi
    # Check legacy scanner PID
    elif [ -f "$LOG_DIR/scanner.pid" ]; then
        local pid=$(cat "$LOG_DIR/scanner.pid")
        if kill -0 $pid 2>/dev/null; then
            log_message "INFO" "Legacy Scanner: ⚠️  Running (PID: $pid) - Only scanning, no trading"
        else
            log_message "WARN" "Legacy Scanner: ❌ Stopped (stale PID file)"
            rm -f "$LOG_DIR/scanner.pid"
        fi
    else
        log_message "INFO" "Trading System: ❌ Not running"
    fi
    
    # Check configuration
    if [ -f "$PROJECT_ROOT/.env" ]; then
        TRADING_MODE=$(grep "TRADING_MODE=" "$PROJECT_ROOT/.env" | cut -d'=' -f2 | tr -d ' ')
        if [ "$TRADING_MODE" = "live" ]; then
            log_message "WARN" "Configuration: ⚠️  LIVE MODE - Real money trading enabled"
        else
            log_message "INFO" "Configuration: ✅ Paper mode - Safe simulation"
        fi
        log_message "INFO" "Configuration: ✅ .env file present"
    else
        log_message "WARN" "Configuration: ❌ .env file missing"
    fi
    
    # Check logs
    if [ -f "$TRADING_LOG" ]; then
        local log_size=$(du -h "$TRADING_LOG" | cut -f1)
        log_message "INFO" "Trading log: $log_size"
    fi
}

show_logs() {
    local log_type=${1:-"trading"}
    
    case $log_type in
        "trading"|"main")
            if [ -f "$TRADING_LOG" ]; then
                log_message "INFO" "📄 Showing trading logs (Ctrl+C to exit)"
                tail -f "$TRADING_LOG"
            else
                log_message "WARN" "Trading log file not found: $TRADING_LOG"
            fi
            ;;
        "error"|"err")
            if [ -f "$ERROR_LOG" ]; then
                log_message "INFO" "📄 Showing error logs (Ctrl+C to exit)"
                tail -f "$ERROR_LOG"
            else
                log_message "WARN" "Error log file not found: $ERROR_LOG"
            fi
            ;;
        "all")
            log_message "INFO" "📄 Showing all logs (Ctrl+C to exit)"
            tail -f "$LOG_DIR"/*.log
            ;;
        *)
            log_message "ERROR" "Unknown log type: $log_type"
            echo "Usage: $0 logs [trading|error|all]"
            exit 1
            ;;
    esac
}

backup_data() {
    log_message "INFO" "💾 Creating backup..."
    
    local backup_dir="$PROJECT_ROOT/backups"
    local timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_file="trading_backup_$timestamp.tar.gz"
    
    mkdir -p "$backup_dir"
    
    # Backup runtime data and configs
    cd "$PROJECT_ROOT"
    tar -czf "$backup_dir/$backup_file" \
        runtime/ \
        configs/ \
        .env 2>/dev/null || tar -czf "$backup_dir/$backup_file" runtime/ configs/
    
    log_message "INFO" "Backup created: $backup_dir/$backup_file"
    
    # Clean old backups (keep last 7 days)
    find "$backup_dir" -name "trading_backup_*.tar.gz" -mtime +7 -delete
}

setup_environment() {
    log_message "INFO" "🚀 Setting up Upbit Trading System environment..."
    
    cd "$PROJECT_ROOT"
    
    # Run setup
    if [ -f "Makefile" ]; then
        log_message "INFO" "📦 Installing dependencies..."
        make setup
    else
        log_message "WARN" "Makefile not found, running manual setup..."
        python3 -m venv .venv
        source .venv/bin/activate
        pip install --upgrade pip
        pip install -e .[dev]
    fi
    
    # Create .env file
    if [ ! -f ".env" ] && [ -f ".env.example" ]; then
        log_message "INFO" "📋 Creating .env configuration file..."
        cp .env.example .env
        log_message "INFO" "✅ .env file created from template"
    fi
    
    # Create directories
    mkdir -p runtime/logs runtime/reports runtime/data
    
    log_message "INFO" "🎉 Setup completed!"
    log_message "WARN" "⚠️  Next steps:"
    log_message "INFO" "1. Edit .env file with your API keys: nano .env"
    log_message "INFO" "2. Test the setup: $0 health"
    log_message "INFO" "3. Start the system: $0 start"
}

show_help() {
    echo "Upbit Trading System - Server Manager"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  setup           Set up the environment (run this first!)"
    echo "  start           Start the trading system scanner"
    echo "  stop            Stop all running services"
    echo "  restart         Restart all services"
    echo "  status          Show system status"
    echo "  health          Run health check"
    echo "  logs [type]     Show logs (trading|error|all)"
    echo "  backup          Create data backup"
    echo "  help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 setup        # First time setup"
    echo "  $0 start        # Start scanner"
    echo "  $0 logs trading # View trading logs"
    echo "  $0 health       # Test API connectivity"
    echo ""
}

# Main command dispatcher
case "${1:-}" in
    "setup")
        setup_environment
        ;;
    "start")
        start_scanner
        ;;
    "stop")
        stop_scanner
        ;;
    "restart")
        stop_scanner
        sleep 2
        start_scanner
        ;;
    "status")
        show_status
        ;;
    "health")
        run_health_check
        ;;
    "logs")
        show_logs "$2"
        ;;
    "backup")
        backup_data
        ;;
    "help"|"--help"|"-h")
        show_help
        ;;
    *)
        echo "Error: Unknown command '$1'"
        echo ""
        show_help
        exit 1
        ;;
esac
