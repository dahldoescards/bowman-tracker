#!/bin/bash
# Database Backup Script for Bowman Draft Tracker
# Usage: ./backup_db.sh [backup_dir]
#
# Requires DATABASE_URL environment variable to be set
# Example: DATABASE_URL=postgresql://user:pass@host:5432/dbname ./backup_db.sh

set -e

BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/bowman_tracker_${TIMESTAMP}.sql"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo "Error: DATABASE_URL environment variable is not set"
    echo "Usage: DATABASE_URL=postgresql://user:pass@host:5432/dbname ./backup_db.sh"
    exit 1
fi

# Extract connection details from DATABASE_URL
# Format: postgresql://user:password@host:port/database
if [[ $DATABASE_URL =~ postgresql://([^:]+):([^@]+)@([^:]+):([^/]+)/(.+) ]]; then
    DB_USER="${BASH_REMATCH[1]}"
    DB_PASS="${BASH_REMATCH[2]}"
    DB_HOST="${BASH_REMATCH[3]}"
    DB_PORT="${BASH_REMATCH[4]}"
    DB_NAME="${BASH_REMATCH[5]}"
else
    echo "Error: Could not parse DATABASE_URL"
    exit 1
fi

echo "Starting database backup..."
echo "  Database: $DB_NAME"
echo "  Host: $DB_HOST"
echo "  Backup file: $BACKUP_FILE"

# Run pg_dump with password in PGPASSWORD env
PGPASSWORD="$DB_PASS" pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --no-owner \
    --no-acl \
    -f "$BACKUP_FILE"

# Compress the backup
gzip "$BACKUP_FILE"
COMPRESSED_FILE="${BACKUP_FILE}.gz"

# Calculate sizes
BACKUP_SIZE=$(ls -lh "$COMPRESSED_FILE" | awk '{print $5}')

echo ""
echo "Backup completed successfully!"
echo "  File: $COMPRESSED_FILE"
echo "  Size: $BACKUP_SIZE"

# Optional: Keep only last 7 backups
MAX_BACKUPS=7
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*.sql.gz 2>/dev/null | wc -l)

if [ "$BACKUP_COUNT" -gt "$MAX_BACKUPS" ]; then
    echo ""
    echo "Cleaning up old backups (keeping last $MAX_BACKUPS)..."
    ls -1t "$BACKUP_DIR"/*.sql.gz | tail -n +$((MAX_BACKUPS + 1)) | xargs rm -f
    echo "  Removed $((BACKUP_COUNT - MAX_BACKUPS)) old backup(s)"
fi

echo ""
echo "Backup complete!"
