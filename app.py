from flask import Flask, request, jsonify, render_template, url_for, redirect, send_from_directory, current_app
import os
import time
import logging
import datetime
from urllib.parse import quote, urlparse
from functools import wraps
from scrapers import ScraperFactory
from scrapers import BaseScraper
from version import VERSION, BUILD_DATE # Make sure version.py exists
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from typing import Callable, Any, Dict, Tuple, Optional

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
        RATELIMIT_API_SITES=os.environ.get('GAMESTORE_API_RATELIMIT_SITES', '200 per hour')
    )
    
    # Override with environment variables
    app.config['CACHE_DIR'] = os.environ.get('GAMESTORE_CACHE_DIR', app.config['CACHE_DIR'])
    app.config['CACHE_TIMEOUT'] = int(os.environ.get('GAMESTORE_CACHE_TIMEOUT', app.config['CACHE_TIMEOUT']))
    app.config['DEFAULT_SITE'] = os.environ.get('GAMESTORE_DEFAULT_SITE', app.config['DEFAULT_SITE'])
    app.config['DEBUG'] = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

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
        # Ensure default_site_id always has a value
        default_site = app.config.get('DEFAULT_SITE', 'gamepciso') # Provide a fallback default
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