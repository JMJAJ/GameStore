"""
Base scraper class for the GameStore application.
"""
import requests
from bs4 import BeautifulSoup, Tag, NavigableString
import logging
import os
import time
from urllib.parse import urlparse, urljoin
from typing import Optional, Dict, Any, List, Union

# Configure logging
logger = logging.getLogger(__name__)

class BaseScraper:
    """
    Base scraper class that defines common functionality for all scrapers.
    """
    
    # These should be overridden by subclasses as CLASS attributes
    site_id: Optional[str] = None
    site_name: Optional[str] = None
    site_description: Optional[str] = None
    
    def __init__(self, base_url: Optional[str] = None, cache_dir: Optional[str] = None, cache_timeout: int = 3600):
        """
        Initialize the scraper.
        
        Args:
            base_url (str, optional): The base URL of the site.
            cache_dir (str, optional): Directory to cache responses.
            cache_timeout (int, optional): Cache timeout in seconds. Defaults to 3600 (1 hour).
        """
        # Use the class attributes if base_url is not provided in constructor,
        # or allow overriding via constructor.
        self.base_url: Optional[str] = base_url or getattr(self.__class__, 'base_url', None)
        self.cache_dir: Optional[str] = cache_dir
        self.cache_timeout: int = cache_timeout
        
        self.headers: Dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "DNT": "1", # Do Not Track
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # The checks for site_id and site_name are more relevant for the factory
        # or for direct instantiation. Removing from here as BaseScraper itself
        # won't have them set. Subclasses are expected to define them as class attributes.
        # if not self.site_id: # self.site_id here refers to BaseScraper.site_id
        #     logger.warning(f"{self.__class__.__name__} does not have site_id set.")
        # if not self.site_name:
        #     logger.warning(f"{self.__class__.__name__} does not have site_name set.")
            
        if self.cache_dir and not os.path.exists(self.cache_dir):
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
            except OSError as e:
                logger.error(f"Failed to create cache directory {self.cache_dir}: {e}")
                self.cache_dir = None # Disable caching if directory creation fails
    
    def _get_cache_path(self, url: str) -> Optional[str]:
        """Generate a filesystem-safe cache path for the URL"""
        # Use class's site_id for cache path prefixing
        class_site_id = getattr(self.__class__, 'site_id', 'unknown_site')
        if not self.cache_dir or not class_site_id:
            return None
            
        parsed = urlparse(url)
        netloc_safe = "".join(c if c.isalnum() or c in ['-', '.'] else '_' for c in parsed.netloc)
        path_safe = "".join(c if c.isalnum() or c in ['-', '_', '.'] else '_' for c in parsed.path.replace('/', '_'))

        filename_base = f"{class_site_id}_{netloc_safe}{path_safe}"
        if parsed.query:
            query_hash = str(abs(hash(parsed.query)) % 1000000) 
            filename_base += '_' + query_hash
        
        max_len = 200 
        if len(filename_base) > max_len:
            filename_base = filename_base[:max_len-10] + "_" + str(abs(hash(filename_base)) % 100000)

        return os.path.join(self.cache_dir, f"{filename_base}.html")
    
    def _is_cache_valid(self, cache_path: str) -> bool:
        """Check if the cache file is still valid"""
        if not os.path.exists(cache_path):
            return False
            
        if self.cache_timeout <= 0: 
            return True

        try:
            mod_time = os.path.getmtime(cache_path)
            current_time = time.time()
            
            if current_time - mod_time > self.cache_timeout:
                logger.debug(f"Cache expired for {cache_path}")
                return False
        except OSError as e:
            logger.warning(f"Error accessing cache file {cache_path} stats: {e}")
            return False 
                
        return True
    
    def _get_soup(self, url: str, force_refresh: bool = False) -> Optional[BeautifulSoup]:
        """
        Get BeautifulSoup object for the given URL.
        
        Args:
            url (str): URL to fetch.
            force_refresh (bool): Force refresh even if cache exists.
            
        Returns:
            Optional[BeautifulSoup]: Parsed HTML, or None on failure.
        """
        cache_path = self._get_cache_path(url)
        
        if cache_path and not force_refresh and self._is_cache_valid(cache_path):
            logger.info(f"Loading from cache: {url}")
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                return BeautifulSoup(html_content, 'html.parser')
            except Exception as e:
                logger.warning(f"Error reading cache file {cache_path}: {e}. Attempting refresh.")
        
        try:
            logger.info(f"Fetching from web: {url}")
            response = requests.get(url, headers=self.headers, timeout=15) 
            response.raise_for_status()
            html_content = response.text
            
            if cache_path:
                try:
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    logger.debug(f"Saved to cache: {cache_path}")
                except Exception as e:
                    logger.warning(f"Error writing to cache file {cache_path}: {e}")
            
            return BeautifulSoup(html_content, 'html.parser')
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            if cache_path and os.path.exists(cache_path):
                logger.info(f"Using stale cache as fallback for {url}")
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                    return BeautifulSoup(html_content, 'html.parser')
                except Exception as read_e:
                    logger.warning(f"Error reading stale cache file {cache_path}: {read_e}")
            return None 
        except Exception as e: 
            logger.error(f"An unexpected error occurred while processing {url}: {e}")
            return None

    def _extract_text(self, soup_or_element: Union[BeautifulSoup, Tag], selector: str, default: str = "") -> str:
        """Extract text from an element"""
        if not soup_or_element:
            return default
        element = soup_or_element.select_one(selector)
        return element.get_text(strip=True) if element else default
    
    def _extract_all_texts(self, soup_or_element: Union[BeautifulSoup, Tag], selector: str) -> List[str]:
        """Extract texts from all matching elements"""
        if not soup_or_element:
            return []
        elements = soup_or_element.select(selector)
        return [el.get_text(strip=True) for el in elements if el.get_text(strip=True)]

    def _extract_attr(self, soup_or_element: Union[BeautifulSoup, Tag], selector: str, attr: str, default: Optional[str] = None) -> Optional[str]:
        """Extract an attribute from an element"""
        if not soup_or_element:
            return default
        element = soup_or_element.select_one(selector)
        if element and element.has_attr(attr):
            value = element[attr]
            if isinstance(value, list): 
                value = value[0] if value else ''

            # Use self.base_url (which might be instance-specific or from class) for normalization
            current_base_url = self.base_url 
            if value and current_base_url:
                if attr in ['src', 'href'] and not value.startswith(('http://', 'https://', 'data:')):
                    if value.startswith('//'):
                        parsed_base = urlparse(current_base_url)
                        return f"{parsed_base.scheme}:{value}"
                    return urljoin(current_base_url, value)
            return value
        return default
        
    def _extract_image(self, soup_or_element: Union[BeautifulSoup, Tag], selector: str) -> Optional[str]:
        """Extract image URL from an element"""
        return self._extract_attr(soup_or_element, selector, 'src')
        
    def _extract_link(self, soup_or_element: Union[BeautifulSoup, Tag], selector: str) -> Optional[str]:
        """Extract link URL from an element"""
        return self._extract_attr(soup_or_element, selector, 'href')
    
    def _format_game_data(self, title: str, url: str, image: Optional[str] = None, 
                          description: Optional[str] = None, release_date: Optional[str] = None) -> Dict[str, Any]:
        """Format game data consistently for all scrapers"""
        return {
            "title": title.strip() if title else "Unknown Title",
            "url": url,
            "image": image,
            "description": description.strip() if description else None,
            "release_date": release_date.strip() if release_date else None,
            "site": getattr(self.__class__, 'site_id', 'unknown_site') # Use class site_id
        }
        
    def clear_cache(self) -> None:
        """Clear the cache for this scraper"""
        class_site_id = getattr(self.__class__, 'site_id', None)
        if not self.cache_dir or not class_site_id:
            logger.info(f"Cache directory or site_id not set for {self.__class__.__name__}. Cannot clear cache.")
            return
            
        prefix = f"{class_site_id}_"
        cleared_count = 0
        error_count = 0
        try:
            for filename in os.listdir(self.cache_dir):
                if filename.startswith(prefix):
                    try:
                        os.remove(os.path.join(self.cache_dir, filename))
                        cleared_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete cache file {filename}: {e}")
                        error_count += 1
        except FileNotFoundError:
            logger.info(f"Cache directory {self.cache_dir} not found for {class_site_id}. Nothing to clear.")
            return
        logger.info(f"Cache cleared for {class_site_id}: {cleared_count} files removed, {error_count} errors.")
    
    def get_games_list(self, page: int = 1, category: Optional[str] = None) -> tuple[List[Dict[str, Any]], bool, List[Dict[str, str]]]:
        raise NotImplementedError(f"{self.__class__.__name__} must implement get_games_list")
    
    def get_game_details(self, url: str) -> tuple[Dict[str, Any], Optional[str], Optional[str], List[str], List[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
        raise NotImplementedError(f"{self.__class__.__name__} must implement get_game_details")
    
    def search_games(self, query: str) -> List[Dict[str, Any]]:
        raise NotImplementedError(f"{self.__class__.__name__} must implement search_games")

    def _normalize_url(self, url_to_normalize: str, base_url_override: Optional[str] = None) -> Optional[str]:
        """
        Normalize a URL by making it absolute.
        """
        if not url_to_normalize:
            return None
            
        if url_to_normalize.startswith(('http://', 'https://', 'data:')):
            return url_to_normalize
            
        effective_base_url = base_url_override or self.base_url # self.base_url comes from constructor
        if not effective_base_url:
            # Fallback to class-level base_url if instance one isn't set
            effective_base_url = getattr(self.__class__, 'base_url', None)

        if not effective_base_url:
            logger.warning(f"Cannot normalize relative URL '{url_to_normalize}' without a base URL for {self.__class__.__name__}.")
            return url_to_normalize 

        if url_to_normalize.startswith('//'):
            parsed_base = urlparse(effective_base_url)
            return f"{parsed_base.scheme}:{url_to_normalize}"
            
        return urljoin(effective_base_url, url_to_normalize)