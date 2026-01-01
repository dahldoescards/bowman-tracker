"""
Production configuration for Bowman Draft Box Tracker.
Centralized config management with environment variable support.
"""

import os
from datetime import timedelta

class Config:
    """Base configuration."""
    
    # Application
    APP_NAME = "Bowman Draft Box Tracker"
    VERSION = "1.0.0"
    
    # Server
    HOST = os.environ.get('HOST', '127.0.0.1')
    PORT = int(os.environ.get('PORT', 5000))
    DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'
    
    # Database
    DATABASE_PATH = os.environ.get('DATABASE_PATH', 
        os.path.join(os.path.dirname(__file__), 'sales_history.db'))
    
    # Security
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')
    
    # Rate limiting (requests per minute)
    RATE_LIMIT_PER_MINUTE = int(os.environ.get('RATE_LIMIT_PER_MINUTE', 60))
    
    # Scheduler
    FETCH_INTERVAL_HOURS = int(os.environ.get('FETCH_INTERVAL_HOURS', 1))
    AUTO_START_SCHEDULER = os.environ.get('AUTO_START_SCHEDULER', 'false').lower() == 'true'
    
    # Data filtering
    MIN_SALE_DATE = os.environ.get('MIN_SALE_DATE', '2025-11-01')
    
    # Proxy settings
    PROXY_FILE = os.environ.get('PROXY_FILE', 
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 'proxies.txt'))
    
    # Cache settings
    SUMMARY_CACHE_TTL = int(os.environ.get('SUMMARY_CACHE_TTL', 60))  # seconds
    CHART_CACHE_TTL = int(os.environ.get('CHART_CACHE_TTL', 30))  # seconds
    
    # API limits
    MAX_SALES_LIMIT = 500
    DEFAULT_SALES_LIMIT = 100


class ProductionConfig(Config):
    """Production-specific settings."""
    DEBUG = False
    
    # Stricter rate limiting in production
    RATE_LIMIT_PER_MINUTE = 30


class DevelopmentConfig(Config):
    """Development-specific settings."""
    DEBUG = True
    RATE_LIMIT_PER_MINUTE = 120


def get_config():
    """Get appropriate config based on environment."""
    env = os.environ.get('FLASK_ENV', 'development')
    if env == 'production':
        return ProductionConfig()
    return DevelopmentConfig()
