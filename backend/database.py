"""
Database schema and connection management for Bowman Draft Box Tracker.
Stores historical sales with duplicate prevention using eBay product ID from URL.

Supports both SQLite (development) and PostgreSQL (production).
Set DATABASE_URL environment variable to use PostgreSQL.
"""

import os
import sys
import signal
import atexit
import threading
import logging
from datetime import datetime
from contextlib import contextmanager
import time

# Configure logging
logger = logging.getLogger(__name__)

# Check for PostgreSQL (production) vs SQLite (development)
DATABASE_URL = os.environ.get('DATABASE_URL')
USE_POSTGRES = DATABASE_URL is not None and DATABASE_URL.startswith('postgres')

# Connection pool for PostgreSQL
_pg_pool = None
_pool_lock = threading.Lock()

if USE_POSTGRES:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor
    # Fix for Railway/Heroku postgres:// vs postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
else:
    import sqlite3
    DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'sales_history.db')

# Thread-local storage for SQLite connections
_local = threading.local()

# Simple in-memory cache for summary data
_cache = {
    'summary': {'data': None, 'timestamp': 0},
    'sales_count': {'data': None, 'timestamp': 0}
}
_cache_lock = threading.Lock()
CACHE_TTL = 60  # seconds

# Track if we're shutting down
_shutting_down = False


def init_connection_pool():
    """Initialize PostgreSQL connection pool."""
    global _pg_pool
    if USE_POSTGRES and _pg_pool is None:
        with _pool_lock:
            if _pg_pool is None:
                try:
                    _pg_pool = pool.ThreadedConnectionPool(
                        minconn=2,
                        maxconn=10,
                        dsn=DATABASE_URL
                    )
                    logger.info("PostgreSQL connection pool initialized")
                except Exception as e:
                    logger.error(f"Failed to create connection pool: {e}")
                    raise


def get_db_connection():
    """Get a database connection (from pool for PostgreSQL, thread-local for SQLite)."""
    if _shutting_down:
        raise RuntimeError("Database is shutting down")
    
    if USE_POSTGRES:
        if _pg_pool is None:
            init_connection_pool()
        return _pg_pool.getconn()
    else:
        if not hasattr(_local, 'connection') or _local.connection is None:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrent read/write performance
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA cache_size=10000')
            conn.execute('PRAGMA temp_store=MEMORY')
            _local.connection = conn
        return _local.connection


def return_connection(conn):
    """Return a PostgreSQL connection to the pool."""
    if USE_POSTGRES and _pg_pool is not None and conn is not None:
        try:
            _pg_pool.putconn(conn)
        except Exception as e:
            logger.warning(f"Error returning connection to pool: {e}")



def get_cursor(conn):
    """Get appropriate cursor for the database type."""
    if USE_POSTGRES:
        return conn.cursor(cursor_factory=RealDictCursor)
    return conn.cursor()


def placeholder(index=None):
    """Return appropriate placeholder for SQL queries."""
    if USE_POSTGRES:
        return '%s'
    return '?'


def placeholders(count):
    """Return multiple placeholders for SQL queries."""
    p = '%s' if USE_POSTGRES else '?'
    return ', '.join([p] * count)



def close_connection():
    """Close thread-local SQLite connection."""
    if hasattr(_local, 'connection') and _local.connection:
        _local.connection.close()
        _local.connection = None


def shutdown():
    """Graceful shutdown - close all connections."""
    global _shutting_down, _pg_pool
    _shutting_down = True
    logger.info("Shutting down database connections...")
    
    # Close PostgreSQL pool
    if USE_POSTGRES and _pg_pool is not None:
        try:
            _pg_pool.closeall()
            logger.info("PostgreSQL connection pool closed")
        except Exception as e:
            logger.error(f"Error closing connection pool: {e}")
    
    # Close SQLite connection
    close_connection()
    logger.info("Database shutdown complete")


# Register shutdown handlers
atexit.register(shutdown)


def _signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown()
    sys.exit(0)


# Register signal handlers (only in main thread)
try:
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
except ValueError:
    # Signal only works in main thread
    pass


@contextmanager
def db_session():
    """Context manager for database sessions with automatic cleanup."""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        # Return PostgreSQL connections to pool
        if USE_POSTGRES:
            return_connection(conn)


def invalidate_cache(cache_key=None):
    """Invalidate cache entries."""
    with _cache_lock:
        if cache_key:
            if cache_key in _cache:
                _cache[cache_key]['timestamp'] = 0
        else:
            for key in _cache:
                _cache[key]['timestamp'] = 0

def init_database():
    """Initialize the database schema."""
    with db_session() as conn:
        cursor = get_cursor(conn)
        
        if USE_POSTGRES:
            # PostgreSQL schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sales (
                    id SERIAL PRIMARY KEY,
                    unique_id TEXT UNIQUE NOT NULL,
                    source TEXT NOT NULL DEFAULT 'ebay',
                    source_url TEXT NOT NULL,
                    ebay_item_id TEXT,
                    title TEXT NOT NULL,
                    sale_price REAL NOT NULL,
                    box_count INTEGER NOT NULL DEFAULT 1,
                    per_box_price REAL NOT NULL,
                    variant_type TEXT NOT NULL CHECK(variant_type IN ('jumbo', 'breakers_delight', 'hobby')),
                    sale_date TEXT NOT NULL,
                    sale_timestamp INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS fetch_history (
                    id SERIAL PRIMARY KEY,
                    fetch_timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    query_term TEXT NOT NULL,
                    total_results INTEGER NOT NULL,
                    new_sales_added INTEGER NOT NULL,
                    duplicates_skipped INTEGER NOT NULL,
                    errors TEXT
                )
            ''')
        else:
            # SQLite schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    unique_id TEXT UNIQUE NOT NULL,
                    source TEXT NOT NULL DEFAULT 'ebay',
                    source_url TEXT NOT NULL,
                    ebay_item_id TEXT,
                    title TEXT NOT NULL,
                    sale_price REAL NOT NULL,
                    box_count INTEGER NOT NULL DEFAULT 1,
                    per_box_price REAL NOT NULL,
                    variant_type TEXT NOT NULL,
                    sale_date TEXT NOT NULL,
                    sale_timestamp INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    
                    CHECK(variant_type IN ('jumbo', 'breakers_delight', 'hobby'))
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS fetch_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetch_timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    query_term TEXT NOT NULL,
                    total_results INTEGER NOT NULL,
                    new_sales_added INTEGER NOT NULL,
                    duplicates_skipped INTEGER NOT NULL,
                    errors TEXT
                )
            ''')
        
        # Create indexes (same syntax for both)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sales_variant_type 
            ON sales(variant_type)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sales_sale_timestamp 
            ON sales(sale_timestamp)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sales_unique_id 
            ON sales(unique_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sales_ebay_item_id 
            ON sales(ebay_item_id)
        ''')
        
        print("Database initialized successfully.")

def check_duplicate(unique_id: str) -> bool:
    """Check if a sale with this unique_id already exists."""
    with db_session() as conn:
        cursor = get_cursor(conn)
        p = placeholder()
        cursor.execute(f'SELECT 1 FROM sales WHERE unique_id = {p}', (unique_id,))
        return cursor.fetchone() is not None

def insert_sale(sale_data: dict) -> bool:
    """
    Insert a new sale record. Returns True if inserted, False if duplicate.
    
    sale_data should contain:
    - unique_id: str (eBay item ID or URL hash)
    - source: str
    - source_url: str
    - ebay_item_id: str (optional)
    - title: str
    - sale_price: float
    - box_count: int
    - per_box_price: float
    - variant_type: str ('jumbo', 'breakers_delight', 'hobby')
    - sale_date: str (YYYY-MM-DD)
    - sale_timestamp: int (Unix timestamp)
    """
    try:
        with db_session() as conn:
            cursor = get_cursor(conn)
            p = placeholders(12)
            cursor.execute(f'''
                INSERT INTO sales (
                    unique_id, source, source_url, ebay_item_id, title,
                    sale_price, box_count, per_box_price, variant_type,
                    sale_date, sale_timestamp, created_at
                ) VALUES ({p})
            ''', (
                sale_data['unique_id'],
                sale_data.get('source', 'ebay'),
                sale_data['source_url'],
                sale_data.get('ebay_item_id'),
                sale_data['title'],
                sale_data['sale_price'],
                sale_data['box_count'],
                sale_data['per_box_price'],
                sale_data['variant_type'],
                sale_data['sale_date'],
                sale_data['sale_timestamp'],
                datetime.now().isoformat()
            ))
            invalidate_cache()  # Clear summary cache on new inserts
            return True
    except Exception as e:
        # Handle both SQLite and PostgreSQL integrity errors
        if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
            return False
        raise


def delete_sales_from_date(from_date: str) -> int:
    """
    Delete all sales from a specific date onwards.
    
    Args:
        from_date: Date string in YYYY-MM-DD format (e.g., '2026-01-01')
    
    Returns:
        Number of sales deleted
    """
    with db_session() as conn:
        cursor = get_cursor(conn)
        p = placeholder()
        
        # First count how many will be deleted
        # Use alias for PostgreSQL RealDictCursor compatibility
        cursor.execute(f'SELECT COUNT(*) as cnt FROM sales WHERE sale_date >= {p}', (from_date,))
        result = cursor.fetchone()
        # Handle both dict (PostgreSQL) and tuple (SQLite) results
        count = result['cnt'] if isinstance(result, dict) else result[0]
        
        # Delete the sales
        cursor.execute(f'DELETE FROM sales WHERE sale_date >= {p}', (from_date,))
        
        invalidate_cache()
        logger.info(f"Deleted {count} sales from {from_date} onwards")
        return count


def get_sale_by_id(sale_id: str) -> dict:
    """Get a single sale by its unique_id."""
    with db_session() as conn:
        cursor = get_cursor(conn)
        p = placeholder()
        cursor.execute(f'SELECT * FROM sales WHERE unique_id = {p}', (sale_id,))
        result = cursor.fetchone()
        return dict(result) if result else None


def update_sale_record(sale_id: str, updates: dict) -> bool:
    """
    Update specific fields of a sale record.
    
    Args:
        sale_id: The unique_id of the sale
        updates: Dict of field -> value to update
    
    Returns:
        True if updated, False if sale not found
    """
    if not updates:
        return False
    
    with db_session() as conn:
        cursor = get_cursor(conn)
        p = placeholder()
        
        # Build SET clause
        set_parts = []
        values = []
        for field, value in updates.items():
            set_parts.append(f"{field} = {p}")
            values.append(value)
        
        set_clause = ', '.join(set_parts)
        values.append(sale_id)  # For WHERE clause
        
        cursor.execute(f'UPDATE sales SET {set_clause} WHERE unique_id = {p}', tuple(values))
        
        if cursor.rowcount > 0:
            invalidate_cache()
            logger.info(f"Updated sale {sale_id}: {updates}")
            return True
        return False

def get_sales_by_variant(variant_type: str, start_date: str = None, end_date: str = None) -> list:
    """
    Get all sales for a specific variant type, optionally filtered by date range.
    Returns list of sale records ordered by sale_timestamp.
    """
    with db_session() as conn:
        cursor = get_cursor(conn)
        p = placeholder()
        
        query = f'SELECT * FROM sales WHERE variant_type = {p}'
        params = [variant_type]
        
        if start_date:
            query += f' AND sale_date >= {p}'
            params.append(start_date)
        
        if end_date:
            query += f' AND sale_date <= {p}'
            params.append(end_date)
        
        query += ' ORDER BY sale_timestamp ASC'
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

def get_all_sales(start_date: str = None, end_date: str = None) -> list:
    """Get all sales, optionally filtered by date range."""
    with db_session() as conn:
        cursor = get_cursor(conn)
        p = placeholder()
        
        query = 'SELECT * FROM sales WHERE 1=1'
        params = []
        
        if start_date:
            query += f' AND sale_date >= {p}'
            params.append(start_date)
        
        if end_date:
            query += f' AND sale_date <= {p}'
            params.append(end_date)
        
        query += ' ORDER BY sale_timestamp ASC'
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

def get_sales_summary() -> dict:
    """Get summary statistics for all variants including cases vs boxes breakdown.
    Results are cached for CACHE_TTL seconds to improve performance.
    """
    # Check cache first
    with _cache_lock:
        cache_entry = _cache['summary']
        if cache_entry['data'] and (time.time() - cache_entry['timestamp']) < CACHE_TTL:
            return cache_entry['data']
    
    with db_session() as conn:
        cursor = get_cursor(conn)
        
        cursor.execute('''
            SELECT 
                variant_type,
                COUNT(*) as total_sales,
                AVG(per_box_price) as avg_price,
                MIN(per_box_price) as min_price,
                MAX(per_box_price) as max_price,
                MIN(sale_date) as earliest_sale,
                MAX(sale_date) as latest_sale,
                SUM(CASE WHEN box_count > 1 THEN 1 ELSE 0 END) as cases_sold,
                SUM(CASE WHEN box_count = 1 THEN 1 ELSE 0 END) as boxes_sold,
                SUM(box_count) as total_boxes
            FROM sales
            GROUP BY variant_type
        ''')
        
        results = {}
        for row in cursor.fetchall():
            results[row['variant_type']] = {
                'total_sales': row['total_sales'],
                'avg_price': round(row['avg_price'], 2) if row['avg_price'] else 0,
                'min_price': row['min_price'],
                'max_price': row['max_price'],
                'earliest_sale': row['earliest_sale'],
                'latest_sale': row['latest_sale'],
                'cases_sold': row['cases_sold'] or 0,
                'boxes_sold': row['boxes_sold'] or 0,
                'total_boxes': row['total_boxes'] or 0
            }
        
        # Update cache
        with _cache_lock:
            _cache['summary'] = {'data': results, 'timestamp': time.time()}
        
        return results

def record_fetch(query_term: str, total_results: int, new_sales: int, duplicates: int, errors: str = None):
    """Record a data fetch operation for monitoring."""
    with db_session() as conn:
        cursor = get_cursor(conn)
        p = placeholders(5)
        cursor.execute(f'''
            INSERT INTO fetch_history (query_term, total_results, new_sales_added, duplicates_skipped, errors)
            VALUES ({p})
        ''', (query_term, total_results, new_sales, duplicates, errors))

def get_latest_fetch_stats() -> dict:
    """Get the most recent fetch statistics."""
    with db_session() as conn:
        cursor = get_cursor(conn)
        cursor.execute('''
            SELECT * FROM fetch_history 
            ORDER BY fetch_timestamp DESC 
            LIMIT 10
        ''')
        return [dict(row) for row in cursor.fetchall()]


def cleanup_old_data(retention_days: int = 180):
    """
    Remove sales and fetch history older than retention_days.
    Default is 180 days (6 months).
    
    Returns dict with counts of deleted records.
    """
    from datetime import datetime, timedelta
    
    cutoff_date = (datetime.now() - timedelta(days=retention_days)).strftime('%Y-%m-%d')
    deleted = {'sales': 0, 'fetch_history': 0}
    
    with db_session() as conn:
        cursor = get_cursor(conn)
        p = placeholder()
        
        # Delete old sales
        cursor.execute(f'DELETE FROM sales WHERE sale_date < {p}', (cutoff_date,))
        deleted['sales'] = cursor.rowcount
        
        # Delete old fetch history
        cursor.execute(f'DELETE FROM fetch_history WHERE fetch_timestamp < {p}', (cutoff_date,))
        deleted['fetch_history'] = cursor.rowcount
        
        if deleted['sales'] > 0 or deleted['fetch_history'] > 0:
            invalidate_cache()
            logger.info(f"Data retention: deleted {deleted['sales']} sales, {deleted['fetch_history']} fetch records older than {cutoff_date}")
    
    return deleted


def get_database_stats() -> dict:
    """Get database statistics for monitoring."""
    with db_session() as conn:
        cursor = get_cursor(conn)
        
        cursor.execute('SELECT COUNT(*) as count FROM sales')
        sales_count = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM fetch_history')
        fetch_count = cursor.fetchone()['count']
        
        cursor.execute('SELECT MIN(sale_date) as oldest, MAX(sale_date) as newest FROM sales')
        date_range = cursor.fetchone()
        
        return {
            'total_sales': sales_count,
            'total_fetches': fetch_count,
            'oldest_sale': date_range['oldest'],
            'newest_sale': date_range['newest'],
            'database_type': 'PostgreSQL' if USE_POSTGRES else 'SQLite'
        }


if __name__ == '__main__':
    init_database()
    print("Database schema created successfully!")
