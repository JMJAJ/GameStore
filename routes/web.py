# routes/web.py
from flask import Blueprint, request, render_template, redirect, url_for, current_app, abort
import logging
from typing import Optional, Any, Dict, List, Tuple, Set
from scrapers import ScraperFactory, BaseScraper
import asyncio
import re # Import re for normalization

logger = logging.getLogger(__name__)
web_bp = Blueprint('web', __name__, template_folder='../templates', static_folder='../static')

# --- Helper functions (_get_factory, _get_site_info, _get_all_scrapers) remain the same ---
def _get_factory() -> ScraperFactory:
    factory = current_app.config.get('scraper_factory')
    if not factory: abort(500, description="Scraper factory not initialized.")
    return factory

def _get_site_info() -> List[Dict[str, str]]: return _get_factory().get_site_info()

def _get_all_scrapers() -> Dict[str, BaseScraper]:
    factory = _get_factory()
    return factory.get_all_scrapers(current_app.config['CACHE_DIR'], current_app.config['CACHE_TIMEOUT'])

# --- Routes: home, games_redirect, view_games_all, view_game remain the same ---
@web_bp.route('/')
def home() -> Any: return redirect(url_for('web.view_games_all', page=1))
@web_bp.route('/games')

def games_redirect() -> Any: return redirect(url_for('web.view_games_all', page=1))

@web_bp.route('/games/all/<int:page>')
def view_games_all(page: int) -> Any:
    dark_mode: str = request.cookies.get('dark_mode', 'false')
    site_info = _get_site_info()
    all_scrapers = _get_all_scrapers()
    all_games: List[Dict[str, Any]] = []
    errors: List[str] = []
    overall_has_next = False
    default_site_id = current_app.config.get('DEFAULT_SITE', 'gamepciso')
    for site_id, scraper in all_scrapers.items():
        try:
            logger.info(f"Fetching page {page} from {site_id}...")
            games, has_next, _ = scraper.get_games_list(page=page, category=None)
            all_games.extend(games)
            if has_next: overall_has_next = True
            logger.info(f"Fetched {len(games)} games from {site_id}. Has Next: {has_next}")
            
            all_games.sort(key=lambda g: (g.get('title') or '').lower())
            return render_template('index.html',
                                   games=all_games, page=page, has_next=overall_has_next,
                                   categories=[], current_category=None, dark_mode=dark_mode,
                                   site='all', sites=site_info, fetch_errors=errors,
                                   default_site_id=default_site_id) # Pass default site id
        except Exception as e:
            logger.error(f"Error in view_games_all page {page}: {e}", exc_info=True)
            return render_template('error.html',
                                   message=f"Error loading games list: {str(e)}",
                                   dark_mode=dark_mode,
                                   site='all', # Indicate 'all' mode even for error
                                   sites=site_info,
                                   default_site_id=default_site_id)
    all_games.sort(key=lambda g: (g.get('title') or '').lower())
    return render_template('index.html', games=all_games, page=page, has_next=overall_has_next, categories=[], current_category=None, dark_mode=dark_mode, site='all', sites=site_info, fetch_errors=errors)

@web_bp.route('/game')
def view_game() -> Any:
    game_url: Optional[str] = request.args.get('url')
    site_param: Optional[str] = request.args.get('site')
    dark_mode: str = request.cookies.get('dark_mode', 'false')
    site_info = _get_site_info()
    default_site_id = current_app.config.get('DEFAULT_SITE', 'gamepciso')

    if not game_url or not site_param:
        return redirect(url_for('web.view_games_all', page=1))

    factory = _get_factory()
    scraper = factory.get_scraper(site_param, current_app.config['CACHE_DIR'], current_app.config['CACHE_TIMEOUT'])

    if not scraper:
        return render_template('error.html', message=f"Unknown site specified: {site_param}",
                               dark_mode=dark_mode, site=site_param, sites=site_info,
                               default_site_id=default_site_id) # Pass default
    try:
        meta, description, sysreq, screenshots, downloads, password, related = scraper.get_game_details(game_url)
        if not meta.get("title") or meta.get("title") == "Unknown Game":
             return render_template('error.html', message=f"Could not load details for the specified game from {scraper.site_name}.",
                                    dark_mode=dark_mode, site=site_param, sites=site_info,
                                    default_site_id=default_site_id) # Pass default
        
        return render_template('game.html', meta=meta, description=description, sysreq=sysreq, screenshots=screenshots,
                       downloads=downloads, password=password, related=related, dark_mode=dark_mode,
                       site=site_param, sites=site_info,
                       default_site_id=default_site_id) # Pass default
    
    except Exception as e:
        logger.error(f"Error in view_game for URL '{game_url}' on site '{site_param}': {e}", exc_info=True)
        return render_template('error.html', message=f"Error loading game details from {scraper.site_name}: {str(e)}",
                               dark_mode=dark_mode, site=site_param, sites=site_info,
                               default_site_id=default_site_id) # Pass default

@web_bp.route('/search')
def search() -> Any:
    query: Optional[str] = request.args.get('q')
    dark_mode: str = request.cookies.get('dark_mode', 'false')
    site_info = _get_site_info()
    default_site_id = current_app.config.get('DEFAULT_SITE', 'gamepciso')

    if not query: return redirect(url_for('web.view_games_all', page=1))

    all_scrapers = _get_all_scrapers()
    raw_results: List[Dict[str, Any]] = []
    errors: List[str] = []

    # --- Step 1: Fetch results from all scrapers ---
    # (Could be parallelized with asyncio for better performance)
    for site_id, scraper in all_scrapers.items():
        try:
            logger.info(f"Searching {site_id} for '{query}'...")
            results = scraper.search_games(query)
            logger.info(f"Found {len(results)} raw results from {site_id}.")
            raw_results.extend(results) # Add site info which is done by _format_game_data
        except NotImplementedError:
             logger.warning(f"Search not implemented for {scraper.site_name}.")
        except Exception as e:
            error_msg = f"Error searching {scraper.site_name}: {e}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)

    # --- Step 2: Normalize titles and group results ---
    def normalize_title(title: str) -> str:
        if not title: return ""
        # Lowercase, remove common suffixes/punctuation, extra spaces
        norm = title.lower()
        norm = re.sub(r'\b(the|a|an)\b', '', norm) # Remove articles
        norm = re.sub(r'[:\'",.&!?()-]', '', norm) # Remove punctuation
        norm = re.sub(r'\s+', ' ', norm).strip() # Collapse whitespace
        # Remove common edition markers for comparison
        norm = re.sub(r'\b(enhanced|deluxe|complete|ultimate|goty|game of the year|edition|remastered|definitive|gold|repack)\b', '', norm)
        norm = re.sub(r'\b(multi\d*|elamigos|gog|rune)\b', '', norm) # Remove release group tags
        norm = re.sub(r'\s+', ' ', norm).strip() # Collapse again
        return norm

    grouped_results: Dict[str, List[Dict[str, Any]]] = {}
    for game in raw_results:
        original_title = game.get('title')
        if not original_title: continue # Skip games without titles

        norm_title = normalize_title(original_title)
        if not norm_title: continue # Skip if normalization results in empty string

        if norm_title not in grouped_results:
            grouped_results[norm_title] = []
        grouped_results[norm_title].append(game)

    # --- Step 3: Score and Sort Groups ---
    def score_match(game_title: str, query: str) -> int:
        score = 0
        title_lower = game_title.lower()
        query_lower = query.lower()
        if query_lower == title_lower:
            score += 100 # Perfect match
        elif query_lower in title_lower:
            score += 50 + (len(query) * 5) # Contains query
            if title_lower.startswith(query_lower):
                score += 20 # Starts with query is better
        # Add more scoring logic if needed (e.g., word matching, TF-IDF)
        # Bonus for having an image
        if game.get('image'):
             score += 5
        return score

    scored_groups: List[Tuple[int, str, List[Dict[str, Any]]]] = []
    query_norm = query.lower()
    for norm_title, games_in_group in grouped_results.items():
        best_score_in_group = 0
        for game in games_in_group:
             current_score = score_match(game.get('title', ''), query_norm)
             best_score_in_group = max(best_score_in_group, current_score)
             game['score'] = current_score # Store score for potential later use

        # Only include groups where at least one title actually contains the query
        if best_score_in_group > 0:
             # Sort games within the group by score (desc) then title (asc)
             games_in_group.sort(key=lambda g: (-g.get('score', 0), (g.get('title') or '').lower()))
             scored_groups.append((best_score_in_group, norm_title, games_in_group))

    # Sort groups by the best score within them (descending), then alphabetically
    scored_groups.sort(key=lambda item: (-item[0], item[1]))

    # --- Step 4: Prepare final list (e.g., take the best entry from each group) ---
    final_results: List[Dict[str, Any]] = []
    MAX_RESULTS = 50 # Limit total results shown
    for score, norm_title, games_in_group in scored_groups:
        if not games_in_group: continue
        # Select the best scored game from the group (already sorted)
        best_game = games_in_group[0]
        # Optional: Add other sources to the best game entry if needed for display
        # best_game['other_sources'] = games_in_group[1:]
        final_results.append(best_game)
        if len(final_results) >= MAX_RESULTS:
             break

    logger.info(f"Processed {len(raw_results)} raw results into {len(final_results)} de-duplicated & sorted results for query '{query}'.")

    try:
        final_results.sort(key=lambda g: (-g.get('score', 0), (g.get('title') or '').lower()))
        return render_template('search.html',
                               games=final_results, query=query, dark_mode=dark_mode,
                               site='all', sites=site_info, fetch_errors=errors,
                               default_site_id=default_site_id) # Pass default
    except Exception as e:
         logger.error(f"Error during search for '{query}': {e}", exc_info=True)
         return render_template('error.html', message=f"Error performing search: {str(e)}",
                                dark_mode=dark_mode, site='all', sites=site_info,
                                default_site_id=default_site_id) # Pass default

@web_bp.route('/api-docs')
def api_docs_page() -> str:
    dark_mode: str = request.cookies.get('dark_mode', 'false')
    site_info = _get_site_info()
    default_site_id = current_app.config.get('DEFAULT_SITE', 'gamepciso')
    return render_template('api_docs.html', dark_mode=dark_mode, sites=site_info, default_site_id=default_site_id)