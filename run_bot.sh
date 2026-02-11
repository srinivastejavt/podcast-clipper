#!/bin/bash
#
# Podcast Clipper - Production Runner
# Auto-restarts on crash, handles network errors
#
# Usage:
#   ./run_bot.sh          - Run in foreground
#   ./run_bot.sh start    - Run in background
#   ./run_bot.sh stop     - Stop the bot
#   ./run_bot.sh status   - Check if running
#

cd "$(dirname "$0")"
LOCKFILE="data/bot.lock"
LOGFILE="bot.log"
PIDFILE="data/runner.pid"

# Ensure data directory exists
mkdir -p data

# Kill any python bot instances
kill_bot() {
    pkill -9 -f "python.*main.py" 2>/dev/null
    rm -f "$LOCKFILE"
}

# Cleanup handler
cleanup() {
    echo ""
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Shutting down..."
    kill_bot
    rm -f "$PIDFILE"
    exit 0
}

# Check if already running
is_running() {
    if [ -f "$PIDFILE" ]; then
        pid=$(cat "$PIDFILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# Handle commands
case "$1" in
    start)
        if is_running; then
            echo "Bot is already running (PID: $(cat $PIDFILE))"
            exit 1
        fi
        echo "Starting bot in background..."
        nohup "$0" > /dev/null 2>&1 &
        echo $! > "$PIDFILE"
        sleep 2
        if is_running; then
            echo "Bot started (PID: $(cat $PIDFILE))"
            echo "Logs: tail -f $LOGFILE"
        else
            echo "Failed to start bot"
            exit 1
        fi
        exit 0
        ;;
    stop)
        if is_running; then
            pid=$(cat "$PIDFILE")
            echo "Stopping bot (PID: $pid)..."
            kill "$pid" 2>/dev/null
            kill_bot
            rm -f "$PIDFILE"
            echo "Bot stopped"
        else
            echo "Bot is not running"
            kill_bot  # Clean up any orphaned processes
        fi
        exit 0
        ;;
    status)
        if is_running; then
            echo "Bot is running (PID: $(cat $PIDFILE))"
            echo "Last log entries:"
            tail -5 "$LOGFILE" 2>/dev/null
        else
            echo "Bot is not running"
        fi
        exit 0
        ;;
    restart)
        "$0" stop
        sleep 2
        "$0" start
        exit 0
        ;;
esac

# Running in foreground mode
trap cleanup SIGINT SIGTERM

# Kill existing instances first
kill_bot
sleep 2

echo "=== Podcast Clipper Bot ==="
echo "Starting with auto-restart..."
echo "Press Ctrl+C to stop"
echo ""

# Store our PID
echo $$ > "$PIDFILE"

# Activate venv
source venv/bin/activate

# Restart counter for exponential backoff
restart_count=0
max_restart_delay=300  # 5 minutes max

# Run with auto-restart
while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting bot..."

    python main.py 2>&1 | tee -a "$LOGFILE"

    EXIT_CODE=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot exited with code $EXIT_CODE"

    # Clean up lock file
    rm -f "$LOCKFILE"

    # Calculate restart delay with exponential backoff
    if [ $EXIT_CODE -eq 0 ]; then
        # Clean exit, reset counter
        restart_count=0
        restart_delay=30
    else
        # Error exit, increase delay
        restart_count=$((restart_count + 1))
        restart_delay=$((30 * restart_count))
        if [ $restart_delay -gt $max_restart_delay ]; then
            restart_delay=$max_restart_delay
        fi
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restarting in $restart_delay seconds... (attempt $restart_count)"
    sleep $restart_delay

    # Reset counter after successful long run
    if [ $restart_count -gt 5 ]; then
        # Check if last run was longer than 10 minutes
        restart_count=0
    fi
done
