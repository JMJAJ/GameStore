      
# GameStore Catalog

GameStore Catalog is a Flask-based web application that scrapes game information from various websites, providing a unified interface to browse, search, and view details about PC games. It features a web UI and a JSON API.

## Features

-   **Multi-Site Scraping:** Supports scraping from multiple game websites (e.g., OvaGames, GamePCISO).
-   **Pluggable Scraper Architecture:** Easily add new scrapers for different sites via the `ScraperFactory`.
-   **Web Interface:**
    -   Browse games with pagination.
    -   Filter games by category (if supported by the scraper).
    -   View detailed game information (description, system requirements, screenshots, download links, passwords).
    -   Search for games across the selected site.
    -   Dark mode support.
-   **JSON API:**
    -   Endpoints to get a list of games, game details, search results, and available sites.
    -   API versioning (e.g., `/api/v1/...`).
    -   Rate limiting.
-   **Caching:** Caches scraped data to reduce load on source websites and improve response times.
-   **Configurable:** Cache directory, timeout, and default site can be configured via environment variables.

## Project Structure
```
.
├── app.py # Main Flask application setup
├── scrapers/ # Scraper modules
│ ├── init.py
│ ├── base_scraper.py # Base class for all scrapers
│ ├── ovagames_scraper.py
│ ├── gamepciso_scraper.py
│ ├── alternate_site_scraper.py # Another example/simple scraper for GamePCISO
│ ├── scraper_factory.py # Discovers and provides scraper instances
│ └── scraper_template.py # Template for new scrapers
├── routes/ # Flask Blueprints for web and API routes
│ ├── init.py
│ ├── web.py
│ └── api.py
├── templates/ # HTML templates
│ ├── layout.html
│ ├── index.html # Games list
│ ├── game.html # Game details
│ ├── search.html
│ ├── error.html
│ └── api_docs.html
├── static/ # Static assets
│ ├── css/style.css
│ └── js/api.js # Client-side JS for API interaction
├── version.py # Application version and build date
├── _root.txt # Example selector definitions (informational, for GamePCISO)
├── requirements.txt # Python dependencies
├── .env.example # Example environment variables
└── README.md
```
      
## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd gamestore-catalog
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure environment variables:**
    Copy `.env.example` to `.env` and customize if needed:
    ```bash
    cp .env.example .env
    ```
    Edit `.env`:
    ```env
    # Flask settings
    FLASK_APP=app.py
    FLASK_DEBUG=True # Set to False in production

    # GameStore settings
    # GAMESTORE_CACHE_DIR=./cache  # Optional: custom cache directory
    # GAMESTORE_CACHE_TIMEOUT=3600 # Optional: cache timeout in seconds (1 hour)
    # GAMESTORE_DEFAULT_SITE=gamepciso # Optional: default site to show
    ```

5.  **Create `version.py`:**
    Create a file named `version.py` in the root directory with the following content:
    ```python
    VERSION = "1.1.0"
    BUILD_DATE = "2023-10-27" # Or any relevant date
    ```

6.  **Run the application:**
    ```bash
    flask run
    ```
    The application will typically be available at `http://127.0.0.1:5000/`.

## Configuration

The application can be configured using environment variables, typically set in a `.env` file in the project root.

-   `FLASK_APP`: Set to `app.py`.
-   `FLASK_DEBUG`: `True` for development (enables reloader, debug mode), `False` for production.
-   `GAMESTORE_CACHE_DIR`: Path to the directory for storing cached HTML pages (defaults to `./cache`).
-   `GAMESTORE_CACHE_TIMEOUT`: Cache duration in seconds (defaults to `3600`).
-   `GAMESTORE_DEFAULT_SITE`: The `site_id` of the scraper to use if none is specified (used mainly by API if `site` param is missing).
-   `GAMESTORE_USE_PROXIES`: Set to `True` to enable proxy usage for scraping requests (defaults to `False`). Requires the `free-proxy` library to be installed (`pip install free-proxy`).
-   `GAMESTORE_PROXY_FETCH_COUNT`: How many proxies to attempt to fetch using `free-proxy` on application startup (defaults to `10`). Note that free proxy sources are unreliable, and fewer might be returned.
-   `GAMESTORE_PROXY_REQUIRE_HTTPS`: Set to `True` to only fetch proxies that claim HTTPS support (defaults to `True`). Recommended for scraping HTTPS sites.
-   `GAMESTORE_PROXY_MAX_RETRIES`: How many different fetched proxies to try for a single request before failing (defaults to `3`).
-   `GAMESTORE_API_RATELIMIT_ENABLED`: `True` or `False` to enable API rate limiting.
-   `GAMESTORE_API_RATELIMIT_*`: Rate limit strings for specific API endpoints (e.g., `100 per hour`).

### Proxy Format (No Longer Used)

The application now uses the `free-proxy` library to dynamically fetch proxies if `GAMESTORE_USE_PROXIES` is set to `True`. The `GAMESTORE_PROXY_FILE` setting is no longer used.

## Usage

### Web Interface

Navigate to the application's base URL (e.g., `http://127.0.0.1:5000/`) in your web browser. You can:
-   Switch between different game source sites.
-   Browse games by page.
-   Filter by category (if available for the site).
-   Click on a game to view its details.
-   Use the search bar to find games.
-   Toggle dark mode.

### API

The API documentation is available at the `/api` endpoint (e.g., `http://127.0.0.1:5000/api`). Key endpoints include:
-   `/api/sites`: Get list of available scraping sites.
-   `/api/games?site=<site_id>&page=<num>&category=<slug>`: Get list of games.
-   `/api/game?site=<site_id>&url=<game_page_url>`: Get details for a specific game.
-   `/api/search?site=<site_id>&q=<query>`: Search for games.

Refer to the API documentation page for detailed request/response formats and examples.

## Adding a New Scraper

1.  Create a new Python file in the `scrapers/` directory (e.g., `newsite_scraper.py`).
2.  In this file, create a class that inherits from `BaseScraper` (see `scrapers/base_scraper.py` and `scrapers/scraper_template.py`).
3.  Implement the required methods:
    -   `__init__(self, ...)`: Set `self.site_id` (unique string), `self.site_name` (display name), and optionally `self.site_description`.
    -   `get_games_list(self, page=1, category=None)`
    -   `get_game_details(self, url)`
    -   `search_games(self, query)`
4.  The `ScraperFactory` will automatically discover and register your new scraper if it's correctly placed and inherits from `BaseScraper`.
5.  Test your scraper thoroughly.