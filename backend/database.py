"""
Database schema and connection management for Bowman Draft Box Tracker.
Stores historical sales with duplicate prevention using eBay product ID from URL.
Optimized for production with connection pooling and caching.
"""

import sqlite3
import os
import threading
from datetime import datetime
from contextlib import contextmanager
from functools import lru_cache
import time

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'sales_history.db')

# Thread-local storage for connections
_local = threading.local()

# Simple in-memory cache for summary data
_cache = {
    'summary': {'data': None, 'timestamp': 0},
    'sales_count': {'data': None, 'timestamp': 0}
}
_cache_lock = threading.Lock()
CACHE_TTL = 60  # seconds


def get_db_connection():
    """Get a thread-local database connection with optimizations."""
    if not hasattr(_local, 'connection') or _local.connection is None:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent read/write performance
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA cache_size=10000')  # ~40MB cache
        conn.execute('PRAGMA temp_store=MEMORY')
        _local.connection = conn
    return _local.connection


def close_connection():
    """Close thread-local connection."""
    if hasattr(_local, 'connection') and _local.connection:
        _local.connection.close()
        _local.connection = None


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
        cursor = conn.cursor()
        
        # Main sales table
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
        
        # Create indexes for efficient querying
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
        
        # Fetch history table for tracking data collection runs
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
        
        print("Database initialized successfully.")

def check_duplicate(unique_id: str) -> bool:
    """Check if a sale with this unique_id already exists."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM sales WHERE unique_id = ?', (unique_id,))
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
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sales (
                    unique_id, source, source_url, ebay_item_id, title,
                    sale_price, box_count, per_box_price, variant_type,
                    sale_date, sale_timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            return True
    except sqlite3.IntegrityError:
        # Duplicate unique_id
        return False

def get_sales_by_variant(variant_type: str, start_date: str = None, end_date: str = None) -> list:
    """
    Get all sales for a specific variant type, optionally filtered by date range.
    Returns list of sale records ordered by sale_timestamp.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        
        query = 'SELECT * FROM sales WHERE variant_type = ?'
        params = [variant_type]
        
        if start_date:
            query += ' AND sale_date >= ?'
            params.append(start_date)
        
        if end_date:
            query += ' AND sale_date <= ?'
            params.append(end_date)
        
        query += ' ORDER BY sale_timestamp ASC'
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

def get_all_sales(start_date: str = None, end_date: str = None) -> list:
    """Get all sales, optionally filtered by date range."""
    with db_session() as conn:
        cursor = conn.cursor()
        
        query = 'SELECT * FROM sales WHERE 1=1'
        params = []
        
        if start_date:
            query += ' AND sale_date >= ?'
            params.append(start_date)
        
        if end_date:
            query += ' AND sale_date <= ?'
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
        cursor = conn.cursor()
        
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
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO fetch_history (query_term, total_results, new_sales_added, duplicates_skipped, errors)
            VALUES (?, ?, ?, ?, ?)
        ''', (query_term, total_results, new_sales, duplicates, errors))

def get_latest_fetch_stats() -> dict:
    """Get the most recent fetch statistics."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM fetch_history 
            ORDER BY fetch_timestamp DESC 
            LIMIT 10
        ''')
        return [dict(row) for row in cursor.fetchall()]

if __name__ == '__main__':
    init_database()
    print("Database schema created successfully!")
