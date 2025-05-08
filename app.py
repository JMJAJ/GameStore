from flask import Flask, request, jsonify, render_template, url_for, redirect, send_from_directory, current_app
import os
import time
import json
import random
import logging
import datetime
import itertools
from urllib.parse import urlparse
from functools import wraps
from scrapers import ScraperFactory
from scrapers import BaseScraper
from version import VERSION, BUILD_DATE # Make sure version.py exists
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from typing import Callable, Any, Dict, List, Tuple, Optional

# --- Import free-proxy ---
try:
    from fp.fp import FreeProxy
    FP_AVAILABLE = True
except ImportError:
    FP_AVAILABLE = False
# -----------------------------

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def nl2br(value):
    """Converts newlines in a string to HTML <br> tags."""
    if not isinstance(value, str): return value
    return re.sub(r'(?:\r\n|\r|\n)', '<br>\n', value)

# NEW: Custom filter to extract hostname
def get_hostname(url_string):
    """Jinja filter to extract hostname from a URL."""
    if not isinstance(url_string, str): return ''
    try:
        parsed = urlparse(url_string)
        hostname = parsed.netloc.replace('www.', '')
        return hostname.split('.')[0]
    except Exception:
        return ''
    
def get_fresh_proxies(count=20, require_https=True, timeout=0.5, rand=True) -> List[Dict[str, Any]]:
    """Fetches a list of fresh proxies using free-proxy."""
    if not FP_AVAILABLE:
        logger.warning("free-proxy library not installed. Cannot fetch proxies.")
        return []

    proxies = []
    logger.info(f"Attempting to fetch {count} fresh proxies (HTTPS required: {require_https})...")
    try:
        # Note: free-proxy can sometimes be slow or fail depending on source sites
        proxy_fetcher = FreeProxy(https=require_https, timeout=timeout, rand=rand)
        # Fetching multiple proxies reliably can be hit or miss with free lists.
        # Let's try fetching one by one up to the count, handling errors.
        fetched_count = 0
        attempts = 0
        max_attempts = count * 3 # Give it more attempts than requested count

        while fetched_count < count and attempts < max_attempts:
            attempts += 1
            try:
                proxy_str = proxy_fetcher.get()
                if proxy_str:
                     # Basic validation and formatting
                     parsed = urlparse(proxy_str)
                     if parsed.scheme and parsed.netloc:
                          proxies.append({
                              'url': proxy_str,
                              'protocol': parsed.scheme,
                              'https_support': parsed.scheme == 'https'
                          })
                          fetched_count +=1
                          # Avoid duplicates (though unlikely with random fetch)
                          proxies = [dict(t) for t in {tuple(d.items()) for d in proxies}]
                          fetched_count = len(proxies)

            except Exception as fetch_err:
                 logger.debug(f"free-proxy get() attempt failed: {fetch_err}")
                 time.sleep(0.1) # Small delay before next attempt
            if attempts % 10 == 0:
                 logger.debug(f"Proxy fetch attempts: {attempts}/{max_attempts}, Found: {fetched_count}")


        if not proxies:
             logger.warning("Failed to fetch any proxies using free-proxy.")
        else:
             logger.info(f"Successfully fetched {len(proxies)} unique proxies.")

    except Exception as e:
        logger.error(f"Error initializing or using FreeProxy: {e}")

    return proxies

# Create Flask application
def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    app = Flask(__name__)
    
    # Default configuration
    app.config.update(
        CACHE_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache'),
        CACHE_TIMEOUT=3600,  # 1 hour in seconds
        DEFAULT_SITE="gamepciso",
        DEBUG=False,
        VERSION=VERSION,
        BUILD_DATE=BUILD_DATE,
        # Rate Limiter Config
        RATELIMIT_API_ENABLED=os.environ.get('GAMESTORE_API_RATELIMIT_ENABLED', 'True').lower() == 'true',
        RATELIMIT_API_GAMES=os.environ.get('GAMESTORE_API_RATELIMIT_GAMES', '100 per hour'),
        RATELIMIT_API_GAME_DETAILS=os.environ.get('GAMESTORE_API_RATELIMIT_GAME_DETAILS', '60 per hour'),
        RATELIMIT_API_SEARCH=os.environ.get('GAMESTORE_API_RATELIMIT_SEARCH', '120 per hour'),
        RATELIMIT_API_SITES=os.environ.get('GAMESTORE_API_RATELIMIT_SITES', '200 per hour'),
        USE_PROXIES=os.environ.get('GAMESTORE_USE_PROXIES', 'False').lower() == 'true',
        PROXY_MAX_RETRIES=int(os.environ.get('GAMESTORE_PROXY_MAX_RETRIES', '3')),
        PROXY_FETCH_COUNT=int(os.environ.get('GAMESTORE_PROXY_FETCH_COUNT', '10')), # How many to fetch initially
        PROXY_REQUIRE_HTTPS=os.environ.get('GAMESTORE_PROXY_REQUIRE_HTTPS', 'True').lower() == 'true', # Prefer HTTPS 
    )
    
    # Override with environment variables
    app.config['CACHE_DIR'] = os.environ.get('GAMESTORE_CACHE_DIR', app.config['CACHE_DIR'])
    app.config['CACHE_TIMEOUT'] = int(os.environ.get('GAMESTORE_CACHE_TIMEOUT', app.config['CACHE_TIMEOUT']))
    app.config['DEFAULT_SITE'] = os.environ.get('GAMESTORE_DEFAULT_SITE', app.config['DEFAULT_SITE'])
    app.config['DEBUG'] = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    # --- Load Proxies using free-proxy ---
    app.config['PROXY_LIST'] = []
    app.config['PROXY_CYCLE'] = None
    if app.config['USE_PROXIES'] and FP_AVAILABLE:
        # Fetch proxies on startup
        proxy_list = get_fresh_proxies(
            count=app.config['PROXY_FETCH_COUNT'],
            require_https=app.config['PROXY_REQUIRE_HTTPS']
            )
        if proxy_list:
            app.config['PROXY_LIST'] = proxy_list
            app.config['PROXY_CYCLE'] = itertools.cycle(proxy_list)
            logger.info(f"Proxy support enabled. Using {len(proxy_list)} proxies fetched via free-proxy.")
        else:
            app.config['USE_PROXIES'] = False
            logger.warning("Proxy usage disabled due to fetch errors or empty list from free-proxy.")
    elif app.config['USE_PROXIES'] and not FP_AVAILABLE:
        logger.warning("GAMESTORE_USE_PROXIES is True, but free-proxy library is not installed. Proxies disabled.")
        app.config['USE_PROXIES'] = False
    else:
         logger.info("Proxy usage is disabled by configuration.")

    # Initialize Flask-Limiter
    limiter = Limiter(
        get_remote_address,
        app=app, # Initialize with app directly
        default_limits=["200 per day", "50 per hour"],
        storage_uri="memory://",
        enabled=app.config['RATELIMIT_API_ENABLED']
    )
    
    # Override with custom configuration if provided
    if config:
        app.config.update(config)
    
    # Ensure cache directory exists
    os.makedirs(app.config['CACHE_DIR'], exist_ok=True)
    
    # Initialize scraper factory
    scraper_factory = ScraperFactory() # This line works
    app.config['scraper_factory'] = scraper_factory
    logger.info(f"ScraperFactory instance created: {scraper_factory}")
    
    # Log discovered scrapers
    logger.info(f"Discovered {len(scraper_factory.scrapers)} scrapers:")
    for site_id_key in scraper_factory.scrapers:
        logger.info(f"  - {site_id_key}")

    # DEBUGGING IMPORT ISSUE:
    import sys
    logger.info("---- DEBUGGING START ----")
    logger.info(f"Current sys.path: {sys.path}")
    logger.info(f"'scrapers' in sys.modules: {'scrapers' in sys.modules}")
    if 'scrapers' in sys.modules:
        import scrapers # Re-import to get the module object
        logger.info(f"scrapers module object: {scrapers}")
        logger.info(f"scrapers.__file__: {getattr(scrapers, '__file__', 'N/A')}")
        logger.info(f"dir(scrapers): {dir(scrapers)}")
        logger.info(f"hasattr(scrapers, 'ScraperFactory'): {hasattr(scrapers, 'ScraperFactory')}")
        if hasattr(scrapers, 'ScraperFactory'):
            logger.info(f"scrapers.ScraperFactory object: {scrapers.ScraperFactory}")
    logger.info("---- DEBUGGING END ----")
    
    # Register blueprints
    from routes.web import web_bp
    from routes.api import api_bp, initialize_limiter_for_api
    
    app.register_blueprint(web_bp)
    initialize_limiter_for_api(limiter)
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # Error handlers
    @app.errorhandler(404)
    def page_not_found(e: Exception) -> Tuple[str, int]:
        """Handle 404 errors"""
        dark_mode = request.cookies.get('dark_mode', 'false')
        if request.blueprint == 'api':
             return jsonify({
                "status": "error",
                "message": "API endpoint not found.",
                "code": "ENDPOINT_NOT_FOUND"
            }), 404
        return render_template('error.html', message="Page not found", dark_mode=dark_mode), 404

    @app.errorhandler(500)
    def server_error(e: Exception) -> Tuple[str, int]:
        """Handle 500 errors"""
        logger.error(f"Server Error: {e}", exc_info=True)
        dark_mode = request.cookies.get('dark_mode', 'false')
        if request.blueprint == 'api':
             return jsonify({
                "status": "error",
                "message": "An internal server error occurred.",
                "code": "INTERNAL_SERVER_ERROR"
            }), 500
        return render_template('error.html', message="Internal server error", dark_mode=dark_mode), 500
    
    @app.errorhandler(429)
    def ratelimit_handler(e: Any) -> Tuple[Dict[str, str], int]:
        """Handle rate limit errors for API"""
        return jsonify(
            status="error",
            message=f"Rate limit exceeded: {e.description}",
            code="RATE_LIMIT_EXCEEDED"
        ), 429

    # Register custom filters
    app.jinja_env.filters['nl2br'] = nl2br
    app.jinja_env.filters['hostname'] = get_hostname # <-- Register the new filter

    # Context processor to add version to all templates
    @app.context_processor
    def inject_global_template_vars() -> Dict[str, Any]:
        default_site = app.config.get('DEFAULT_SITE', 'gamepciso')
        return {
            'version': app.config.get('VERSION', 'N/A'),
            'build_date': app.config.get('BUILD_DATE', 'N/A'),
            'current_year': datetime.datetime.utcnow().year,
            'default_site_id': default_site
        }
        
    return app

# Create application instance for direct running
app = create_app()

# Run the app if executed directly
if __name__ == '__main__':
    logger.info(f"Starting GameStore v{app.config['VERSION']}")
    app.run(debug=app.config['DEBUG'], host='0.0.0.0', port=5000)