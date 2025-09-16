#!/bin/bash
# Paper Trading Startup Script
# Safe paper trading with enhanced Telegram notifications

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/runtime/logs"

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

# Header
echo -e "${CYAN}"
echo "=================================="
echo "📝 PAPER TRADING STARTUP SCRIPT"
echo "=================================="
echo -e "${NC}"

# Check if .env exists
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    log_message "ERROR" ".env file not found"
    log_message "INFO" "Creating .env from template..."
    
    if [ -f "$PROJECT_ROOT/.env.example" ]; then
        cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
        log_message "SUCCESS" ".env file created"
    else
        log_message "ERROR" ".env.example not found"
        exit 1
    fi
fi

# Check if TRADING_MODE is set to paper
CURRENT_MODE=$(grep "TRADING_MODE=" "$PROJECT_ROOT/.env" | cut -d'=' -f2 | tr -d ' ' | tr -d '"')

if [ "$CURRENT_MODE" != "paper" ]; then
    log_message "WARN" "Current trading mode: $CURRENT_MODE"
    log_message "INFO" "Setting trading mode to PAPER for safe testing..."
    
    # Create backup
    cp "$PROJECT_ROOT/.env" "$PROJECT_ROOT/.env.backup.$(date +%Y%m%d_%H%M%S)"
    
    # Update trading mode
    sed -i.bak 's/TRADING_MODE=.*/TRADING_MODE=paper/' "$PROJECT_ROOT/.env"
    rm -f "$PROJECT_ROOT/.env.bak"
    
    log_message "SUCCESS" "Trading mode set to PAPER"
else
    log_message "SUCCESS" "Trading mode already set to PAPER"
fi

# Check Telegram configuration
log_message "INFO" "Checking Telegram configuration..."

TELEGRAM_TOKEN=$(grep "TELEGRAM_BOT_TOKEN=" "$PROJECT_ROOT/.env" | cut -d'=' -f2 | tr -d ' ' | tr -d '"')
TELEGRAM_CHAT=$(grep "TELEGRAM_CHAT_ID=" "$PROJECT_ROOT/.env" | cut -d'=' -f2 | tr -d ' ' | tr -d '"')

if [ -z "$TELEGRAM_TOKEN" ] || [ "$TELEGRAM_TOKEN" = "your_bot_token_here" ]; then
    log_message "WARN" "Telegram bot token not configured"
    log_message "INFO" "Paper trading will work without Telegram notifications"
    echo -e "${YELLOW}💡 To enable Telegram notifications:${NC}"
    echo "   1. Create a bot: @BotFather on Telegram"
    echo "   2. Get your chat ID: @userinfobot"
    echo "   3. Update .env file with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
elif [ -z "$TELEGRAM_CHAT" ] || [ "$TELEGRAM_CHAT" = "your_chat_id_here" ]; then
    log_message "WARN" "Telegram chat ID not configured"
    log_message "INFO" "Paper trading will work without Telegram notifications"
else
    log_message "SUCCESS" "Telegram configuration looks good!"
fi

# Check virtual environment
if [ ! -d "$PROJECT_ROOT/.venv" ]; then
    log_message "ERROR" "Virtual environment not found"
    log_message "INFO" "Run 'make setup' first to initialize the environment"
    exit 1
fi

# Stop any existing processes
log_message "INFO" "Stopping any existing trading processes..."
if [ -f "$PROJECT_ROOT/scripts/server-manager.sh" ]; then
    "$PROJECT_ROOT/scripts/server-manager.sh" stop > /dev/null 2>&1 || true
fi

# Create log directories
mkdir -p "$LOG_DIR"

# Start paper trading with enhanced configuration
log_message "INFO" "Starting Paper Trading System..."
log_message "INFO" "Using paper-trading.yaml configuration for optimal testing"

cd "$PROJECT_ROOT"
source .venv/bin/activate

# Check if paper-trading.yaml exists, otherwise use default config
if [ -f "configs/paper-trading.yaml" ]; then
    CONFIG_FILE="configs/paper-trading.yaml"
    log_message "INFO" "Using optimized paper trading configuration"
else
    CONFIG_FILE="configs/config.yaml"
    log_message "WARN" "Using default configuration (paper-trading.yaml not found)"
fi

# Display startup information
echo -e "${BLUE}"
echo "🚀 PAPER TRADING STARTUP INFO:"
echo "───────────────────────────────"
echo "📁 Project Root: $PROJECT_ROOT"
echo "⚙️  Configuration: $CONFIG_FILE"
echo "📊 Mode: PAPER (Safe Simulation)"
echo "📝 Logs: $LOG_DIR"
echo "🔄 Max Markets: 30 (rate limit optimized)"
echo "💰 Max Position: 1M KRW (test size)"
echo "📱 Telegram: $([ -n "$TELEGRAM_TOKEN" ] && [ "$TELEGRAM_TOKEN" != "your_bot_token_here" ] && echo "Enabled" || echo "Disabled")"
echo -e "${NC}"

# Start the trading system
log_message "INFO" "Launching trading system..."

# Background execution with logging
nohup python3 -m src.app run --mode paper > "$LOG_DIR/paper_trading.log" 2>&1 &
TRADING_PID=$!

# Save PID
echo $TRADING_PID > "$LOG_DIR/paper_trading.pid"

# Wait a moment to check if it started successfully
sleep 3

if kill -0 $TRADING_PID 2>/dev/null; then
    log_message "SUCCESS" "Paper Trading System started successfully!"
    log_message "INFO" "Process ID: $TRADING_PID"
    echo ""
    echo -e "${GREEN}✅ PAPER TRADING IS NOW RUNNING${NC}"
    echo ""
    echo "📋 Useful Commands:"
    echo "   📊 Check status:     ./scripts/server-manager.sh status"
    echo "   📄 View logs:        tail -f $LOG_DIR/paper_trading.log"
    echo "   🛑 Stop trading:     ./scripts/server-manager.sh stop"
    echo "   📱 Test Telegram:    python3 -m src.app test-telegram"
    echo ""
    echo -e "${YELLOW}💡 Monitor the logs for trading activity and tune settings as needed${NC}"
    echo -e "${YELLOW}💡 Paper trading results will help you optimize before going live${NC}"
    echo ""
else
    log_message "ERROR" "Failed to start Paper Trading System"
    log_message "INFO" "Check the logs for details: $LOG_DIR/paper_trading.log"
    exit 1
fi
