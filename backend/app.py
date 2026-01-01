"""
Flask API Server for 2025 Bowman Draft Box Tracker.

Provides REST API endpoints for:
- Retrieving sales data by variant and date range
- Getting summary statistics
- Manual fetch triggers
- Scheduler status and control

Production-ready with gzip compression, rate limiting, and security headers.
"""

import os
import sys
import re
import gzip
import logging
from io import BytesIO
from functools import wraps
from collections import defaultdict
import time
from flask import Flask, jsonify, request, send_from_directory, after_this_request
from datetime import datetime, timedelta

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


@app.after_request
def add_security_headers(response):
    """Add security headers and gzip compression to all responses."""
    # Security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Cache headers
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    else:
        response.headers['Cache-Control'] = 'public, max-age=3600'
    
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


# ============================================================================
# API Routes - Health & Info
# ============================================================================

@app.route('/api/health')
def health_check():
    """Health check endpoint."""
    return jsonify({
        'success': True,
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
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
