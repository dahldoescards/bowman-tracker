"""
Flask API Server for 2025 Bowman Draft Box Tracker.

Provides REST API endpoints for:
- Retrieving sales data by variant and date range
- Getting summary statistics
- Manual fetch triggers
- Scheduler status and control

Production-ready with gzip compression, rate limiting, security headers,
Sentry error monitoring, and Prometheus metrics.
"""

import os
import sys
import re
import gzip
import logging
import time
from functools import wraps
from collections import defaultdict
from flask import Flask, jsonify, request, send_from_directory, redirect
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (
    init_database, get_sales_by_variant, get_all_sales, 
    get_sales_summary, get_latest_fetch_stats
)
from services.scheduler import get_scheduler, run_single_fetch

# Initialize Flask app
app = Flask(__name__, static_folder='../frontend', static_url_path='')

# Initialize Sentry (optional - only if SENTRY_DSN is set)
SENTRY_DSN = os.environ.get('SENTRY_DSN')
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.1,  # 10% of transactions for performance
            environment=os.environ.get('FLASK_ENV', 'development')
        )
        logger.info("Sentry error monitoring initialized")
    except ImportError:
        logger.warning("sentry-sdk not installed, error monitoring disabled")

# Initialize Prometheus metrics (optional)
try:
    from prometheus_flask_exporter import PrometheusMetrics
    metrics = PrometheusMetrics(app, group_by='endpoint')
    # Custom metrics
    metrics.info('app_info', 'Application info', version='1.2.0')
    logger.info("Prometheus metrics enabled at /metrics")
except ImportError:
    metrics = None
    logger.info("prometheus-flask-exporter not installed, metrics disabled")

# Rate limiting configuration
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX_REQUESTS = 60  # requests per window
_rate_limit_data = defaultdict(list)



def rate_limit(f):
    """Simple in-memory rate limiter decorator."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = request.remote_addr or 'unknown'
        current_time = time.time()
        
        # Clean old entries
        _rate_limit_data[client_ip] = [
            t for t in _rate_limit_data[client_ip] 
            if current_time - t < RATE_LIMIT_WINDOW
        ]
        
        # Check rate limit
        if len(_rate_limit_data[client_ip]) >= RATE_LIMIT_MAX_REQUESTS:
            return jsonify({
                'success': False, 
                'error': 'Rate limit exceeded. Please try again later.'
            }), 429
        
        # Record this request
        _rate_limit_data[client_ip].append(current_time)
        
        return f(*args, **kwargs)
    return decorated_function


@app.before_request
def redirect_to_https():
    """Redirect HTTP to HTTPS in production."""
    if os.environ.get('FLASK_ENV') == 'production':
        # Check if request came over HTTP (Railway sets X-Forwarded-Proto)
        if request.headers.get('X-Forwarded-Proto', 'https') == 'http':
            url = request.url.replace('http://', 'https://', 1)
            return redirect(url, code=301)


@app.after_request
def add_security_headers(response):
    """Add security headers, ETag support, and gzip compression."""
    # Security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Content Security Policy - allows only trusted sources
    if not request.path.startswith('/api/'):
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'self'"
        )
        response.headers['Content-Security-Policy'] = csp
    
    # Permissions Policy - disable unnecessary browser features
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    
    # HSTS for HTTPS (only in production)
    if os.environ.get('FLASK_ENV') == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Cache headers with smarter defaults
    if request.path.startswith('/api/'):
        # API responses: short cache with revalidation
        if request.path == '/api/summary':
            # Summary changes slowly, cache for 30 seconds
            response.headers['Cache-Control'] = 'public, max-age=30, stale-while-revalidate=60'
        elif request.path.startswith('/api/chart/'):
            # Chart data, cache for 60 seconds
            response.headers['Cache-Control'] = 'public, max-age=60, stale-while-revalidate=120'
        else:
            response.headers['Cache-Control'] = 'no-store, max-age=0'
    elif request.path.endswith(('.css', '.js')):
        # Static assets: long cache with versioning
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif request.path == '/' or request.path.endswith('.html'):
        # HTML: short cache
        response.headers['Cache-Control'] = 'public, max-age=300'
    else:
        response.headers['Cache-Control'] = 'public, max-age=3600'
    
    # ETag for API responses (enables conditional requests)
    if request.path.startswith('/api/') and response.status_code == 200:
        import hashlib
        data = response.get_data()
        if data:
            etag = hashlib.md5(data).hexdigest()
            response.headers['ETag'] = f'"{etag}"'
            
            # Check If-None-Match header
            if_none_match = request.headers.get('If-None-Match')
            if if_none_match and if_none_match.strip('"') == etag:
                response.status_code = 304
                response.set_data(b'')
                return response
    
    # Gzip compression for large JSON/text responses only
    try:
        content_length = response.content_length or 0
        if (content_length > 500 and
            'gzip' in request.headers.get('Accept-Encoding', '').lower() and
            response.content_type and 
            ('application/json' in response.content_type)):
            
            data = response.get_data()
            if data:
                compressed = gzip.compress(data, compresslevel=6)
                
                if len(compressed) < len(data):
                    response.set_data(compressed)
                    response.headers['Content-Encoding'] = 'gzip'
                    response.headers['Content-Length'] = len(compressed)
    except Exception as e:
        logger.warning(f"Gzip compression failed: {e}")
    
    return response



# Input validation helpers
def validate_date(date_str):
    """Validate date string format YYYY-MM-DD."""
    if not date_str:
        return None
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return None
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return date_str
    except ValueError:
        return None


def validate_variant(variant):
    """Validate variant type."""
    valid = ['jumbo', 'breakers_delight', 'hobby', 'all']
    return variant if variant in valid else None


# Initialize database on startup
init_database()

# Auto-start scheduler if configured (for production)
# Use file-based lock to ensure only ONE worker starts the scheduler
AUTO_START_SCHEDULER = os.environ.get('AUTO_START_SCHEDULER', 'false').lower() == 'true'
SCHEDULER_LOCK_FILE = '/tmp/bowman_scheduler.lock'

if AUTO_START_SCHEDULER:
    import fcntl
    try:
        # Try to acquire exclusive lock
        lock_file = open(SCHEDULER_LOCK_FILE, 'w')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        # Lock acquired - this worker runs the scheduler
        logger.info("AUTO_START_SCHEDULER enabled, starting background data fetcher...")
        scheduler = get_scheduler()
        scheduler.start()
        logger.info(f"Scheduler started, will fetch data every {scheduler.interval} seconds")
        
        # Keep lock file open to maintain the lock
    except (IOError, OSError):
        # Another worker already has the lock
        logger.info("Scheduler already running in another worker, skipping...")


# ============================================================================
# Static File Routes
# ============================================================================

@app.route('/')
def serve_frontend():
    """Serve the main frontend page."""
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    """Serve static files."""
    return send_from_directory(app.static_folder, path)


# ============================================================================
# API Routes - Sales Data
# ============================================================================

@app.route('/api/sales')
@rate_limit
def get_sales():
    """
    Get all sales with optional filtering.
    
    Query params:
    - variant: Filter by variant type (jumbo, breakers_delight, hobby)
    - start_date: Start date (YYYY-MM-DD)
    - end_date: End date (YYYY-MM-DD)
    - limit: Maximum number of results (max 500)
    """
    variant = validate_variant(request.args.get('variant'))
    start_date = validate_date(request.args.get('start_date'))
    end_date = validate_date(request.args.get('end_date'))
    limit = request.args.get('limit', type=int)
    
    # Cap limit at 500 for performance
    if limit and limit > 500:
        limit = 500
    
    if variant and variant != 'all':
        sales = get_sales_by_variant(variant, start_date, end_date)
    else:
        sales = get_all_sales(start_date, end_date)
    
    if limit:
        sales = sales[:limit]
    
    return jsonify({
        'success': True,
        'count': len(sales),
        'sales': sales
    })


@app.route('/api/sales/<variant>')
def get_sales_for_variant(variant):
    """Get sales for a specific variant type."""
    if variant not in ['jumbo', 'breakers_delight', 'hobby']:
        return jsonify({'success': False, 'error': 'Invalid variant type'}), 400
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    sales = get_sales_by_variant(variant, start_date, end_date)
    
    return jsonify({
        'success': True,
        'variant': variant,
        'count': len(sales),
        'sales': sales
    })


@app.route('/api/chart/<variant>')
def get_chart_data(variant):
    """
    Get time-series data formatted for charting.
    
    Returns data points with:
    - timestamp
    - price (per-box)
    - volume (count of sales at that price on that date)
    """
    if variant not in ['jumbo', 'breakers_delight', 'hobby', 'all']:
        return jsonify({'success': False, 'error': 'Invalid variant type'}), 400
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if variant == 'all':
        sales = get_all_sales(start_date, end_date)
    else:
        sales = get_sales_by_variant(variant, start_date, end_date)
    
    # Format for charting - include all individual data points
    chart_data = []
    for sale in sales:
        chart_data.append({
            'x': sale['sale_timestamp'] * 1000,  # JavaScript timestamp
            'y': sale['per_box_price'],
            'date': sale['sale_date'],
            'title': sale['title'],
            'box_count': sale['box_count'],
            'total_price': sale['sale_price'],
            'variant': sale['variant_type']
        })
    
    # Also calculate daily aggregates for volume analysis
    daily_stats = {}
    for sale in sales:
        date = sale['sale_date']
        if date not in daily_stats:
            daily_stats[date] = {
                'date': date,
                'count': 0,
                'total_value': 0,
                'prices': []
            }
        daily_stats[date]['count'] += 1
        daily_stats[date]['total_value'] += sale['per_box_price']
        daily_stats[date]['prices'].append(sale['per_box_price'])
    
    # Calculate daily averages
    for date, stats in daily_stats.items():
        stats['avg_price'] = round(stats['total_value'] / stats['count'], 2)
        stats['min_price'] = min(stats['prices'])
        stats['max_price'] = max(stats['prices'])
        del stats['prices']  # Remove raw prices list
    
    return jsonify({
        'success': True,
        'variant': variant,
        'data_points': chart_data,
        'daily_stats': list(daily_stats.values())
    })


@app.route('/api/summary')
def get_summary():
    """Get summary statistics for all variants."""
    summary = get_sales_summary()
    
    # Add total counts
    total_sales = sum(v.get('total_sales', 0) for v in summary.values())
    
    return jsonify({
        'success': True,
        'summary': summary,
        'total_sales': total_sales,
        'variants_tracked': list(summary.keys())
    })


# ============================================================================
# API Routes - Scheduler Control
# ============================================================================

@app.route('/api/scheduler/status')
def scheduler_status():
    """Get current scheduler status."""
    scheduler = get_scheduler()
    status = scheduler.get_status()
    
    # Add recent fetch history
    status['recent_fetches'] = get_latest_fetch_stats()
    
    return jsonify({
        'success': True,
        'status': status
    })


@app.route('/api/scheduler/start', methods=['POST'])
def start_scheduler():
    """Start the scheduler."""
    scheduler = get_scheduler()
    scheduler.start()
    
    return jsonify({
        'success': True,
        'message': 'Scheduler started',
        'status': scheduler.get_status()
    })


@app.route('/api/scheduler/stop', methods=['POST'])
def stop_scheduler():
    """Stop the scheduler."""
    scheduler = get_scheduler()
    scheduler.stop()
    
    return jsonify({
        'success': True,
        'message': 'Scheduler stopped',
        'status': scheduler.get_status()
    })


@app.route('/api/fetch', methods=['POST'])
def trigger_fetch():
    """Manually trigger a data fetch."""
    try:
        stats = run_single_fetch()
        return jsonify({
            'success': True,
            'message': 'Fetch completed',
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/refetch', methods=['POST'])
def refetch_from_date():
    """Delete sales from a date and re-fetch. Requires secret key."""
    # Simple protection - require a secret key
    provided_key = request.headers.get('X-Refetch-Key') or request.json.get('key')
    expected_key = os.environ.get('SECRET_KEY', '')
    
    if not expected_key or provided_key != expected_key:
        return jsonify({
            'success': False,
            'error': 'Invalid or missing refetch key'
        }), 403
    
    from_date = request.json.get('from_date')
    if not from_date or not validate_date(from_date):
        return jsonify({
            'success': False,
            'error': 'Invalid date format. Use YYYY-MM-DD'
        }), 400
    
    try:
        from database import delete_sales_from_date
        
        # Delete sales from that date onwards
        deleted_count = delete_sales_from_date(from_date)
        
        # Run a fresh fetch
        fetch_stats = run_single_fetch()
        
        return jsonify({
            'success': True,
            'message': f'Deleted {deleted_count} sales from {from_date} and re-fetched',
            'deleted_count': deleted_count,
            'fetch_stats': fetch_stats
        })
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f"Refetch failed: {e}\n{error_traceback}")
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': error_traceback
        }), 500

# ============================================================================
# API Routes - Health & Info
# ============================================================================

@app.route('/api/health')
def health_check():
    """Health check endpoint with database stats."""
    try:
        from database import get_database_stats
        db_stats = get_database_stats()
        db_healthy = True
    except Exception as e:
        db_stats = {'error': str(e)}
        db_healthy = False
    
    return jsonify({
        'success': True,
        'status': 'healthy' if db_healthy else 'degraded',
        'timestamp': datetime.now().isoformat(),
        'database': db_stats,
        'version': '1.2.0'
    })



@app.route('/api/info')
def api_info():
    """API information and available endpoints."""
    return jsonify({
        'name': '2025 Bowman Draft Box Tracker API',
        'version': '1.0.0',
        'endpoints': {
            'GET /api/sales': 'Get all sales with optional filtering',
            'GET /api/sales/<variant>': 'Get sales for specific variant',
            'GET /api/chart/<variant>': 'Get chart-formatted time series data',
            'GET /api/summary': 'Get summary statistics',
            'GET /api/scheduler/status': 'Get scheduler status',
            'POST /api/scheduler/start': 'Start the scheduler',
            'POST /api/scheduler/stop': 'Stop the scheduler',
            'POST /api/fetch': 'Trigger manual data fetch',
            'GET /api/health': 'Health check'
        },
        'variants': ['jumbo', 'breakers_delight', 'hobby']
    })


# ============================================================================
# Error Handlers
# ============================================================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({'success': False, 'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Bowman Draft Tracker API Server')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--auto-schedule', action='store_true', help='Auto-start scheduler')
    
    args = parser.parse_args()
    
    # Optionally start scheduler
    if args.auto_schedule:
        scheduler = get_scheduler()
        scheduler.start()
        print("Scheduler auto-started with hourly fetching")
    
    print(f"\n{'='*60}")
    print(f"  2025 Bowman Draft Box Tracker")
    print(f"  Server running at http://{args.host}:{args.port}")
    print(f"{'='*60}\n")
    
    app.run(host=args.host, port=args.port, debug=args.debug)
