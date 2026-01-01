"""
Scheduler Service for automated hourly data fetching.

Runs on a configurable schedule to fetch new sales data from 130point.
Integrates with the data processing pipeline for:
- Fetching
- Filtering (box sales only)
- Parsing
- Calculating per-box prices
- Deduplicating
- Storing in database
"""

import os
import sys
import time
import threading
import logging
from datetime import datetime
from typing import Callable, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import init_database, insert_sale, check_duplicate, record_fetch
from services.data_fetcher import ProxyManager, load_classifier, fetch_all_queries, PROXY_FILE

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default schedule: every hour
DEFAULT_INTERVAL_SECONDS = 3600


class DataScheduler:
    """Manages scheduled data fetching operations."""
    
    def __init__(self, interval_seconds: int = DEFAULT_INTERVAL_SECONDS):
        self.interval = interval_seconds
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = None
        self.callbacks: list = []
        
        # Initialize components
        self.proxy_manager = ProxyManager(PROXY_FILE)
        self.classifier = load_classifier()
        
        # Initialize database
        init_database()
    
    def add_callback(self, callback: Callable):
        """Add a callback function to be called after each fetch."""
        self.callbacks.append(callback)
    
    def fetch_and_process(self) -> dict:
        """
        Perform a single fetch and process cycle.
        
        Returns stats about the operation.
        """
        start_time = datetime.now()
        logger.info(f"Starting data fetch at {start_time.isoformat()}")
        
        stats = {
            'timestamp': start_time.isoformat(),
            'total_fetched': 0,
            'new_sales': 0,
            'duplicates': 0,
            'errors': [],
            'by_variant': {
                'jumbo': 0,
                'breakers_delight': 0,
                'hobby': 0
            }
        }
        
        try:
            # Fetch all data
            results, fetch_stats = fetch_all_queries(self.proxy_manager, self.classifier)
            stats['total_fetched'] = fetch_stats['box_sales']
            stats['errors'].extend(fetch_stats.get('errors', []))
            
            # Process each result
            for sale_data in results:
                unique_id = sale_data['unique_id']
                
                # Check for duplicate
                if check_duplicate(unique_id):
                    stats['duplicates'] += 1
                    logger.debug(f"Duplicate skipped: {unique_id}")
                    continue
                
                # Filter out sales with unreasonably old dates
                # 2025 Bowman Draft releases Jan 14, 2026 - presales shouldn't be before Nov 2025
                if sale_data.get('sale_date', '') < '2025-11-01':
                    logger.warning(f"Filtered old date: {sale_data['sale_date']} - {sale_data['title'][:50]}")
                    continue
                
                # Insert new sale
                if insert_sale(sale_data):
                    stats['new_sales'] += 1
                    variant = sale_data['variant_type']
                    stats['by_variant'][variant] = stats['by_variant'].get(variant, 0) + 1
                    logger.info(f"New sale: {variant} @ ${sale_data['per_box_price']:.2f}/box")
                else:
                    stats['duplicates'] += 1
            
            # Record fetch in history
            record_fetch(
                query_term='all_variants',
                total_results=stats['total_fetched'],
                new_sales=stats['new_sales'],
                duplicates=stats['duplicates'],
                errors='; '.join(stats['errors']) if stats['errors'] else None
            )
            
        except Exception as e:
            logger.error(f"Fetch cycle error: {e}")
            stats['errors'].append(str(e))
        
        # Update timing
        self.last_run = start_time
        
        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()
        stats['duration_seconds'] = duration
        
        logger.info(f"Fetch complete: {stats['new_sales']} new, {stats['duplicates']} duplicates, {duration:.1f}s")
        
        # Call callbacks
        for callback in self.callbacks:
            try:
                callback(stats)
            except Exception as e:
                logger.error(f"Callback error: {e}")
        
        return stats
    
    def _run_loop(self):
        """Internal loop for scheduled execution."""
        while self.running:
            try:
                self.fetch_and_process()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            
            # Calculate next run time
            self.next_run = datetime.now()
            
            # Sleep in small increments to allow graceful shutdown
            sleep_remaining = self.interval
            while sleep_remaining > 0 and self.running:
                sleep_time = min(10, sleep_remaining)
                time.sleep(sleep_time)
                sleep_remaining -= sleep_time
    
    def start(self):
        """Start the scheduler."""
        if self.running:
            logger.warning("Scheduler already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info(f"Scheduler started with {self.interval}s interval")
    
    def stop(self):
        """Stop the scheduler gracefully."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=15)
        logger.info("Scheduler stopped")
    
    def get_status(self) -> dict:
        """Get current scheduler status."""
        return {
            'running': self.running,
            'interval_seconds': self.interval,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'proxies_loaded': len(self.proxy_manager.proxies),
            'classifier_loaded': self.classifier is not None
        }


# Global scheduler instance
_scheduler: Optional[DataScheduler] = None


def get_scheduler() -> DataScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = DataScheduler()
    return _scheduler


def run_single_fetch() -> dict:
    """Run a single fetch operation immediately."""
    scheduler = get_scheduler()
    return scheduler.fetch_and_process()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Data Scheduler for Bowman Draft Tracker')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    parser.add_argument('--interval', type=int, default=3600, help='Interval in seconds')
    
    args = parser.parse_args()
    
    if args.once:
        print("Running single fetch...")
        stats = run_single_fetch()
        print(f"\nResults:")
        print(f"  New sales: {stats['new_sales']}")
        print(f"  Duplicates: {stats['duplicates']}")
        print(f"  By variant: {stats['by_variant']}")
    else:
        print(f"Starting scheduler with {args.interval}s interval...")
        scheduler = get_scheduler()
        scheduler.interval = args.interval
        scheduler.start()
        
        try:
            while True:
                time.sleep(60)
                status = scheduler.get_status()
                print(f"Status: Last run: {status['last_run']}")
        except KeyboardInterrupt:
            print("\nShutting down...")
            scheduler.stop()
