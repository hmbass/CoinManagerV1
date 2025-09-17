#!/bin/bash

# Live Trading Stop Script
# Safely stops live trading system

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_ROOT/runtime/live_trading.pid"
LOG_DIR="$PROJECT_ROOT/runtime/logs"

# Function to print colored messages
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Check if live trading is running
check_running() {
    if [ ! -f "$PID_FILE" ]; then
        print_message $YELLOW "ℹ️  Live trading is not running (no PID file found)"
        exit 0
    fi
    
    local pid=$(cat "$PID_FILE")
    if ! ps -p "$pid" > /dev/null 2>&1; then
        print_message $YELLOW "ℹ️  Live trading is not running (stale PID file)"
        rm -f "$PID_FILE"
        exit 0
    fi
    
    return 0
}

# Stop live trading
stop_trading() {
    local pid=$(cat "$PID_FILE")
    
    print_message $BLUE "🛑 Stopping live trading (PID: $pid)..."
    
    # Send SIGTERM first (graceful shutdown)
    if kill -TERM "$pid" 2>/dev/null; then
        print_message $BLUE "📤 Sent SIGTERM signal..."
        
        # Wait up to 30 seconds for graceful shutdown
        local count=0
        while [ $count -lt 30 ] && ps -p "$pid" > /dev/null 2>&1; do
            sleep 1
            count=$((count + 1))
            echo -n "."
        done
        echo ""
        
        # Check if process stopped
        if ! ps -p "$pid" > /dev/null 2>&1; then
            print_message $GREEN "✅ Live trading stopped gracefully"
        else
            print_message $YELLOW "⚠️  Graceful shutdown timeout, forcing stop..."
            
            # Force kill if still running
            if kill -KILL "$pid" 2>/dev/null; then
                print_message $YELLOW "💀 Live trading force stopped"
            else
                print_message $RED "❌ Failed to stop live trading process"
                exit 1
            fi
        fi
    else
        print_message $RED "❌ Failed to send stop signal to process"
        exit 1
    fi
    
    # Clean up PID file
    rm -f "$PID_FILE"
}

# Show final status
show_status() {
    print_message $BLUE "📊 Final Status:"
    print_message $GREEN "• Live trading: Stopped"
    print_message $BLUE "• Logs available at: $LOG_DIR/live_trading.log"
    print_message $BLUE "• Error logs: $LOG_DIR/live_error.log"
    print_message $BLUE "• Order logs: $LOG_DIR/live_orders.log"
    
    echo ""
    print_message $YELLOW "💡 To view recent logs:"
    print_message $BLUE "   tail -50 $LOG_DIR/live_trading.log"
    
    echo ""
    print_message $YELLOW "💡 To restart live trading:"
    print_message $BLUE "   ./scripts/start-live-trading.sh"
    
    echo ""
    print_message $GREEN "🛡️  Your account is now safe from automated trading"
}

# Emergency stop function
emergency_stop() {
    print_message $RED "🚨 EMERGENCY STOP 🚨"
    print_message $RED "Killing ALL python processes related to trading..."
    
    # Kill all python processes with our app name
    pkill -f "src.app" 2>/dev/null || true
    
    # Clean up PID file
    rm -f "$PID_FILE"
    
    print_message $YELLOW "⚠️  Emergency stop completed"
    print_message $YELLOW "⚠️  Please check your Upbit account for any open orders"
}

# Main execution
main() {
    print_message $BLUE "🛑 Live Trading Stop"
    print_message $BLUE "==================="
    echo ""
    
    # Check for emergency stop flag
    if [ "$1" = "--emergency" ] || [ "$1" = "-e" ]; then
        emergency_stop
        return
    fi
    
    # Normal stop procedure
    check_running
    
    print_message $YELLOW "⚠️  This will stop live trading"
    print_message $YELLOW "   Any open positions will remain open"
    print_message $YELLOW "   You may need to manually close them in Upbit"
    echo ""
    
    read -p "Continue with stopping live trading? (yes/no): " confirm
    
    if [ "$confirm" = "yes" ]; then
        stop_trading
        show_status
    else
        print_message $GREEN "✅ Stop cancelled - live trading continues"
    fi
}

# Help function
show_help() {
    echo "Live Trading Stop Script"
    echo ""
    echo "Usage:"
    echo "  $0                  # Normal stop (with confirmation)"
    echo "  $0 --emergency      # Emergency stop (immediate, no confirmation)"
    echo "  $0 --help          # Show this help"
    echo ""
    echo "Normal stop:"
    echo "  • Sends graceful shutdown signal"
    echo "  • Waits up to 30 seconds"
    echo "  • Force kills if needed"
    echo ""
    echo "Emergency stop:"
    echo "  • Immediately kills all related processes"
    echo "  • Use only if normal stop fails"
    echo "  • May leave orders in inconsistent state"
}

# Handle command line arguments
case "${1:-}" in
    --help|-h)
        show_help
        exit 0
        ;;
    *)
        main "$@"
        ;;
esac
