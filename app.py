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
    
def load_proxies(proxy_file_path: str) -> List[Dict[str, Any]]:
    """Loads and filters proxies from the new JSON file structure."""
    proxies = []
    try:
        with open(proxy_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Extract the list from the 'proxies' key
        raw_proxies = data.get("proxies", [])
        logger.info(f"Loaded {len(raw_proxies)} raw proxies from {proxy_file_path} (under 'proxies' key)")

        usable_protocols = {'http', 'https', 'socks4', 'socks5'} # Allow SOCKS proxies too

        for p in raw_proxies:
            # Check if the proxy is marked as alive (optional but good)
            if not p.get('alive', False):
                continue

            protocol = p.get('protocol', '').lower()
            ip = p.get('ip')
            port = p.get('port')

            if protocol in usable_protocols and ip and port:
                # Construct the proxy URL string for requests
                # Requests uses http:// for http, https:// for https,
                # socks4:// for SOCKS4, socks5:// for SOCKS5
                if protocol.startswith('socks'):
                    proxy_url = f"{protocol}://{ip}:{port}"
                elif protocol in ['http', 'https']:
                    # For http/https proxies, requests usually expects http:// in the proxy dict key
                    # but the protocol itself tells us if it *can* handle https target sites via connect tunnel
                     proxy_url = f"http://{ip}:{port}" # Use http:// scheme for the proxy definition itself
                else:
                    continue # Skip unknown protocols

                proxies.append({
                    'url': proxy_url, # URL formatted for requests proxy dict value
                    'protocol': protocol, # Original protocol (http, https, socks4, socks5)
                    'supports_https_target': p.get('ssl', False) or protocol == 'https', # Can it proxy HTTPS targets?
                    # You could add anonymity, uptime etc. here if needed for filtering/prioritization
                    'anonymity': p.get('anonymity'),
                    'uptime': p.get('uptime'),
                })

        # Optional: Filter further based on anonymity or uptime
        # initial_count = len(proxies)
        # proxies = [p for p in proxies if p['anonymity'] == 'elite' and p['uptime'] > 50]
        # logger.info(f"Filtered by elite/uptime > 50%: {initial_count} -> {len(proxies)}")

        logger.info(f"Filtered down to {len(proxies)} usable and alive proxies.")

    except FileNotFoundError:
        logger.warning(f"Proxy file not found: {proxy_file_path}. Proxies disabled.")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from proxy file: {proxy_file_path}. Proxies disabled.")
    except Exception as e:
        logger.error(f"An unexpected error occurred loading proxies: {e}. Proxies disabled.")

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
        PROXY_FILE=os.environ.get('GAMESTORE_PROXY_FILE', 'proxy.json'),
        USE_PROXIES=os.environ.get('GAMESTORE_USE_PROXIES', 'False').lower() == 'true',
        PROXY_MAX_RETRIES=int(os.environ.get('GAMESTORE_PROXY_MAX_RETRIES', '3'))
    )
    
    # Override with environment variables
    app.config['CACHE_DIR'] = os.environ.get('GAMESTORE_CACHE_DIR', app.config['CACHE_DIR'])
    app.config['CACHE_TIMEOUT'] = int(os.environ.get('GAMESTORE_CACHE_TIMEOUT', app.config['CACHE_TIMEOUT']))
    app.config['DEFAULT_SITE'] = os.environ.get('GAMESTORE_DEFAULT_SITE', app.config['DEFAULT_SITE'])
    app.config['DEBUG'] = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    # --- Load Proxies using free-proxy ---
    app.config['PROXY_LIST'] = []
    app.config['PROXY_CYCLE'] = None
    if app.config['USE_PROXIES']:
        proxy_list = load_proxies(app.config['PROXY_FILE'])
        if proxy_list:
            app.config['PROXY_LIST'] = proxy_list
            app.config['PROXY_CYCLE'] = itertools.cycle(proxy_list)
            logger.info(f"Proxy support enabled. Using {len(proxy_list)} proxies.")
        else:
            app.config['USE_PROXIES'] = False
            logger.warning("Proxy usage disabled due to loading errors or empty list.")
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