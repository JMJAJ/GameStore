# scrapers/__init__.py
import logging

logger = logging.getLogger(__name__)

from .base_scraper import BaseScraper
from .scraper_factory import ScraperFactory

try:
    from . import ovagames_scraper
except ImportError as e:
    logger.warning(f"Could not import ovagames_scraper module: {e}")

try:
    from . import gamepciso_scraper
except ImportError as e:
    logger.warning(f"Could not import gamepciso_scraper module: {e}")

# Removed reference to alternate_site_scraper

__all__ = [
    'BaseScraper',
    'ScraperFactory',
]