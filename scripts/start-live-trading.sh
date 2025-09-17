#!/bin/bash

# Live Trading Startup Script
# ⚠️  WARNING: This script starts REAL MONEY TRADING
# Please ensure you understand the risks before proceeding

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_ROOT/configs/live-trading.yaml"
LOG_DIR="$PROJECT_ROOT/runtime/logs"
PID_FILE="$PROJECT_ROOT/runtime/live_trading.pid"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Function to print colored messages
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Safety check function
safety_check() {
    print_message $RED "⚠️  LIVE TRADING WARNING ⚠️"
    echo ""
    print_message $YELLOW "This script will start REAL MONEY TRADING with the following settings:"
    echo ""
    echo "• Configuration: $CONFIG_FILE"
    echo "• Risk per trade: 0.2% of account"
    echo "• Daily loss limit: -0.5%"
    echo "• Max position size: 300,000 KRW"
    echo "• Trading sessions:"
    echo "  - Morning: 09:15-12:45 KST"
    echo "  - Evening: 17:15-18:45 KST"
    echo ""
    print_message $RED "YOU CAN LOSE REAL MONEY!"
    echo ""
    
    # Confirm multiple times
    read -p "Type 'I UNDERSTAND THE RISKS' to continue: " confirmation
    if [ "$confirmation" != "I UNDERSTAND THE RISKS" ]; then
        print_message $GREEN "✅ Smart choice! Live trading cancelled."
        exit 0
    fi
    
    echo ""
    read -p "Are you absolutely sure you want to proceed with LIVE TRADING? (yes/no): " final_confirm
    if [ "$final_confirm" != "yes" ]; then
        print_message $GREEN "✅ Live trading cancelled."
        exit 0
    fi
}

# Check if already running
check_running() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            print_message $RED "❌ Live trading is already running (PID: $pid)"
            print_message $BLUE "To stop: ./scripts/stop-live-trading.sh"
            exit 1
        else
            # Stale PID file
            rm -f "$PID_FILE"
        fi
    fi
}

# Environment check
check_environment() {
    print_message $BLUE "🔍 Checking environment..."
    
    # Check if .env exists
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        print_message $RED "❌ .env file not found"
        print_message $YELLOW "Please create .env file with your Upbit API keys"
        exit 1
    fi
    
    # Check if virtual environment exists
    if [ ! -d "$PROJECT_ROOT/.venv" ]; then
        print_message $RED "❌ Virtual environment not found"
        print_message $YELLOW "Run 'make setup' to initialize the environment"
        exit 1
    fi
    
    # Check if config file exists
    if [ ! -f "$CONFIG_FILE" ]; then
        print_message $RED "❌ Live trading config not found: $CONFIG_FILE"
        exit 1
    fi
    
    print_message $GREEN "✅ Environment check passed"
}

# API key check
check_api_keys() {
    print_message $BLUE "🔑 Checking API keys..."
    
    # Source .env file
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
    
    if [ -z "$UPBIT_ACCESS_KEY" ] || [ -z "$UPBIT_SECRET_KEY" ]; then
        print_message $RED "❌ Upbit API keys not configured"
        print_message $YELLOW "Please set UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY in .env file"
        exit 1
    fi
    
    # Basic format check
    if [[ ! "$UPBIT_ACCESS_KEY" =~ ^[A-Za-z0-9]{40}$ ]]; then
        print_message $RED "❌ Invalid UPBIT_ACCESS_KEY format"
        exit 1
    fi
    
    if [[ ! "$UPBIT_SECRET_KEY" =~ ^[A-Za-z0-9+/]{70,}={0,2}$ ]]; then
        print_message $RED "❌ Invalid UPBIT_SECRET_KEY format"
        exit 1
    fi
    
    print_message $GREEN "✅ API keys format validated"
}

# Account balance check
check_balance() {
    print_message $BLUE "💰 Checking account balance..."
    
    # Activate virtual environment
    source "$PROJECT_ROOT/.venv/bin/activate"
    
    # Run balance check
    cd "$PROJECT_ROOT"
    local balance_check=$(python3 -m src.app health --config "$CONFIG_FILE" 2>&1)
    
    if echo "$balance_check" | grep -q "error\|Error\|ERROR"; then
        print_message $RED "❌ Account balance check failed"
        print_message $YELLOW "Details: $balance_check"
        exit 1
    fi
    
    print_message $GREEN "✅ Account balance check passed"
}

# Telegram notification check
check_telegram() {
    print_message $BLUE "📱 Testing Telegram notifications..."
    
    source "$PROJECT_ROOT/.venv/bin/activate"
    cd "$PROJECT_ROOT"
    
    # Test Telegram notification
    local telegram_test=$(python3 -m src.app test-telegram 2>&1)
    
    if echo "$telegram_test" | grep -q "error\|Error\|ERROR\|Failed"; then
        print_message $YELLOW "⚠️  Telegram notification test failed"
        print_message $YELLOW "Live trading will continue without notifications"
        
        read -p "Continue without Telegram notifications? (yes/no): " continue_without_telegram
        if [ "$continue_without_telegram" != "yes" ]; then
            print_message $GREEN "✅ Setup cancelled. Please configure Telegram notifications."
            exit 0
        fi
    else
        print_message $GREEN "✅ Telegram notifications working"
    fi
}

# Start live trading
start_trading() {
    print_message $BLUE "🚀 Starting live trading..."
    
    # Activate virtual environment
    source "$PROJECT_ROOT/.venv/bin/activate"
    cd "$PROJECT_ROOT"
    
    # Start live trading with specific config
    nohup python3 -m src.app run --mode live --config "$CONFIG_FILE" > "$LOG_DIR/live_trading.log" 2>&1 &
    
    # Save PID
    echo $! > "$PID_FILE"
    local pid=$(cat "$PID_FILE")
    
    # Wait a moment and check if process is still running
    sleep 3
    if ps -p "$pid" > /dev/null 2>&1; then
        print_message $GREEN "✅ Live trading started successfully!"
        print_message $BLUE "📊 PID: $pid"
        print_message $BLUE "📋 Logs: tail -f $LOG_DIR/live_trading.log"
        print_message $BLUE "🛑 Stop: ./scripts/stop-live-trading.sh"
        print_message $BLUE "📈 Status: ./scripts/server-manager.sh status"
        
        echo ""
        print_message $RED "⚠️  REMINDER: You are now trading with REAL MONEY!"
        print_message $YELLOW "🔍 Monitor your trades carefully"
        print_message $YELLOW "🛡️  The system has safety limits but USE AT YOUR OWN RISK"
        
    else
        print_message $RED "❌ Failed to start live trading"
        print_message $YELLOW "Check logs: tail -f $LOG_DIR/live_trading.log"
        rm -f "$PID_FILE"
        exit 1
    fi
}

# Main execution
main() {
    print_message $BLUE "🎯 Live Trading Startup"
    print_message $BLUE "======================="
    echo ""
    
    # Run all checks
    safety_check
    echo ""
    check_running
    check_environment
    check_api_keys
    check_balance
    check_telegram
    
    echo ""
    print_message $RED "🚨 FINAL WARNING 🚨"
    print_message $RED "This is your last chance to cancel before starting REAL MONEY TRADING"
    echo ""
    read -p "Proceed with live trading? (yes/no): " final_decision
    
    if [ "$final_decision" = "yes" ]; then
        echo ""
        start_trading
    else
        print_message $GREEN "✅ Live trading cancelled. Good decision!"
        exit 0
    fi
}

# Run main function
main "$@"
