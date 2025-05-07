from flask import Blueprint, request, jsonify, current_app
import logging
from functools import wraps
from typing import Callable, Any, Dict, Optional
from scrapers import BaseScraper # For type hinting
from flask_limiter import Limiter # Import Limiter

# Configure logging
logger = logging.getLogger(__name__)

# Create blueprint
api_bp = Blueprint('api', __name__)

# Global variable to hold the limiter instance for this blueprint
# This will be set by app.py after the app and limiter are created.
blueprint_limiter: Optional[Limiter] = None

def initialize_limiter_for_api(limiter_instance: Limiter):
    global blueprint_limiter
    blueprint_limiter = limiter_instance

# Decorator that will be defined using blueprint_limiter
# We need to define these decorators *after* blueprint_limiter is set,
# or make them dynamically access it.
# This is tricky. A common pattern is to apply decorators inside a function
# that is called during app setup.

# Let's redefine how decorators are applied.
# Instead of applying them directly at the top level,
# we can create functions that return the decorated function.

def limit_games_route(f: Callable) -> Callable:
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    # Apply limiter only if it's initialized
    if blueprint_limiter:
        return blueprint_limiter.limit(lambda: current_app.config.get('RATELIMIT_API_GAMES', '100 per hour'))(decorated)
    return decorated # No rate limit if limiter not set (should not happen in prod)

def limit_game_details_route(f: Callable) -> Callable:
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    if blueprint_limiter:
        return blueprint_limiter.limit(lambda: current_app.config.get('RATELIMIT_API_GAME_DETAILS', '60 per hour'))(decorated)
    return decorated

def limit_search_route(f: Callable) -> Callable:
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    if blueprint_limiter:
        return blueprint_limiter.limit(lambda: current_app.config.get('RATELIMIT_API_SEARCH', '120 per hour'))(decorated)
    return decorated
    
def limit_sites_route(f: Callable) -> Callable:
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    if blueprint_limiter:
        return blueprint_limiter.limit(lambda: current_app.config.get('RATELIMIT_API_SITES', '200 per hour'))(decorated)
    return decorated


# ... (validate_site and handle_api_errors remain the same) ...
def validate_site(f: Callable) -> Callable:
    """Decorator to validate site parameter and provide scraper instance."""
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        site_id_param: Optional[str] = request.args.get('site')
        
        if not site_id_param:
            site_id_param = current_app.config['DEFAULT_SITE']

        scraper_factory = current_app.config['scraper_factory']
        
        scraper: Optional[BaseScraper] = scraper_factory.get_scraper(
            site_id_param, 
            current_app.config['CACHE_DIR'],
            current_app.config['CACHE_TIMEOUT']
        )

        if not scraper:
            return jsonify({
                "status": "error",
                "message": f"Unknown or uninitialized site: {site_id_param}", 
                "code": "SITE_NOT_FOUND"
            }), 400
        
        return f(*args, **kwargs, scraper=scraper)
    return decorated_function


def handle_api_errors(f: Callable) -> Callable:
    """Decorator to handle API errors consistently."""
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        try:
            return f(*args, **kwargs)
        except ValueError as e: 
            logger.warning(f"API Value Error in {f.__name__}: {e}")
            return jsonify({
                "status": "error",
                "message": str(e),
                "code": "INVALID_PARAMETER"
            }), 400
        except NotImplementedError as e:
            logger.warning(f"API Feature Not Implemented in {f.__name__}: {e}")
            return jsonify({
                "status": "error",
                "message": f"This feature is not implemented for the selected site: {str(e)}",
                "code": "NOT_IMPLEMENTED"
            }), 501
        except Exception as e:
            logger.error(f"API Exception in {f.__name__}: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": "An unexpected server error occurred.", 
                "code": "SERVER_ERROR"
            }), 500
    return decorated_function


@api_bp.route('/games')
@limit_games_route # Use the new decorator function
@handle_api_errors
@validate_site 
def api_games(scraper: BaseScraper) -> Any: 
    try:
        page_str = request.args.get('page', '1')
        page = int(page_str)
        if page < 1:
            raise ValueError("Page number must be a positive integer.")
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "Invalid page number provided. Must be an integer.",
            "code": "INVALID_PAGE_NUMBER"
        }), 400

    category: Optional[str] = request.args.get('category')
    
    games, has_next, _ = scraper.get_games_list(page, category)

    return jsonify({
        "status": "success",
        "site": scraper.site_id,
        "games": games,
        "has_next": has_next,
        "current_page": page
    })


@api_bp.route('/game')
@limit_game_details_route
@handle_api_errors
@validate_site 
def api_game(scraper: BaseScraper) -> Any:
    url: Optional[str] = request.args.get('url')
    
    if not url:
        return jsonify({
            "status": "error",
            "message": "URL parameter is required.",
            "code": "MISSING_PARAMETER_URL"
        }), 400
    
    meta, description, sysreq, screenshots, downloads, password, related = scraper.get_game_details(url)

    if not meta.get("title") or meta.get("title") == "Unknown Game": 
        return jsonify({
            "status": "error",
            "message": f"Could not retrieve details for the provided URL from site '{scraper.site_id}'.",
            "code": "DETAILS_NOT_FOUND"
        }), 404

    return jsonify({
        "status": "success",
        "site": scraper.site_id,
        **meta, 
        "description": description,
        "system_requirements": sysreq,
        "screenshots": screenshots,
        "download_links": downloads,
        "download_password": password,
        "related_games": related
    })


@api_bp.route('/search')
@limit_search_route
@handle_api_errors
@validate_site 
def api_search(scraper: BaseScraper) -> Any:
    query: Optional[str] = request.args.get('q')
    
    if not query:
        return jsonify({
            "status": "error",
            "message": "Query parameter 'q' is required.",
            "code": "MISSING_PARAMETER_QUERY"
        }), 400
    
    games: list = scraper.search_games(query)

    return jsonify({
        "status": "success",
        "site": scraper.site_id,
        "query": query,
        "results": games
    })


@api_bp.route('/sites')
@limit_sites_route
@handle_api_errors 
def api_sites() -> Any:
    scraper_factory = current_app.config['scraper_factory']
    site_info: list = scraper_factory.get_site_info()
    
    return jsonify({
        "status": "success",
        "sites": site_info
    })


@api_bp.route('/v1/games')
@limit_games_route
@handle_api_errors
@validate_site 
def api_v1_games(scraper: BaseScraper) -> Any:
    return api_games(scraper=scraper) 


@api_bp.route('/v1/game')
@limit_game_details_route
@handle_api_errors
@validate_site 
def api_v1_game(scraper: BaseScraper) -> Any:
    return api_game(scraper=scraper)


@api_bp.route('/v1/search')
@limit_search_route
@handle_api_errors
@validate_site 
def api_v1_search(scraper: BaseScraper) -> Any:
    return api_search(scraper=scraper)


@api_bp.route('/v1/sites')
@limit_sites_route
@handle_api_errors
def api_v1_sites() -> Any:
    return api_sites()