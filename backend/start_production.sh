#!/bin/bash
# Production startup script for Bowman Draft Box Tracker
# Uses Gunicorn for production WSGI serving

set -e

# Configuration
WORKERS=${WORKERS:-4}
PORT=${PORT:-5000}
HOST=${HOST:-0.0.0.0}
TIMEOUT=${TIMEOUT:-120}

# Ensure we're in the right directory
cd "$(dirname "$0")"

echo "=============================================="
echo " Bowman Draft Box Tracker - Production Server"
echo "=============================================="
echo ""
echo " Workers: $WORKERS"
echo " Host: $HOST"
echo " Port: $PORT"
echo " Timeout: ${TIMEOUT}s"
echo ""

# Check if gunicorn is installed
if ! command -v gunicorn &> /dev/null; then
    echo "Installing gunicorn..."
    pip install gunicorn
fi

# Initialize database if needed
python3 -c "from database import init_database; init_database()"

# Start Gunicorn with production settings
exec gunicorn \
    --workers $WORKERS \
    --bind $HOST:$PORT \
    --timeout $TIMEOUT \
    --access-logfile - \
    --error-logfile - \
    --capture-output \
    --enable-stdio-inheritance \
    --preload \
    "app:app"
