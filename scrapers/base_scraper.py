"""
Base scraper class for the GameStore application.
"""
import requests
from bs4 import BeautifulSoup, Tag
import logging
import os
import time
from urllib.parse import urlparse, urljoin
from typing import Optional, Dict, Any, List, Union
import random # Keep random for potential use later if needed
from flask import current_app # Import current_app to access config

# --- NEW: Import and initialize colorama ---
try:
    import colorama
    from colorama import Fore, Style, Back
    colorama.init(autoreset=True) # Automatically reset style after each print
    COLOR_ENABLED = True
except ImportError:
    # Create dummy Fore, Style objects if colorama is not installed
    class DummyStyle:
        def __getattr__(self, name): return ""
    Fore = DummyStyle()
    Style = DummyStyle()
    Back = DummyStyle()
    COLOR_ENABLED = False
    logging.warning("Colorama not installed, proxy status colors will be disabled.")
# -----------------------------------------

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
        self.base_url: Optional[str] = base_url or getattr(self.__class__, 'base_url', None)
        self.cache_dir: Optional[str] = cache_dir; self.cache_timeout: int = cache_timeout
        self.headers: Dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "DNT": "1", # Do Not Track
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        if self.cache_dir and not os.path.exists(self.cache_dir):
            try: os.makedirs(self.cache_dir, exist_ok=True)
            except OSError as e: logger.error(f"Failed to create cache dir {self.cache_dir}: {e}"); self.cache_dir = None
    
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
        cache_path = self._get_cache_path(url)

        if cache_path and not force_refresh and self._is_cache_valid(cache_path):
            logger.info(f"{Fore.CYAN}CACHE{Style.RESET_ALL}: Loading {url}")
            try:
                with open(cache_path, 'r', encoding='utf-8') as f: html_content = f.read()
                return BeautifulSoup(html_content, 'html.parser')
            except Exception as e:
                logger.warning(f"Error reading cache file {cache_path}: {e}. Attempting refresh.")

        use_proxies = current_app.config.get('USE_PROXIES', False)
        proxy_cycle = current_app.config.get('PROXY_CYCLE') if use_proxies else None
        # Determine number of attempts: proxy retries + 1 final direct attempt if proxies fail
        proxy_retries = current_app.config.get('PROXY_MAX_RETRIES', 3) if use_proxies else 0
        total_attempts = proxy_retries + 1 # Includes the final direct attempt

        target_domain = urlparse(url).netloc or "unknown_target"
        final_direct_attempt_made = False

        for attempt in range(total_attempts):
            current_proxy_url = None
            proxies_dict = None
            is_proxy_attempt = use_proxies and attempt < proxy_retries

            log_prefix = f"Attempt {attempt + 1}/{total_attempts}"

            if is_proxy_attempt and proxy_cycle:
                try:
                    proxy_info = next(proxy_cycle)
                    current_proxy_url = proxy_info['url']
                    target_scheme = urlparse(url).scheme
                    proxies_dict = {target_scheme: current_proxy_url}
                    proxy_ip = urlparse(current_proxy_url).netloc
                    logger.info(f"{log_prefix}: {Style.DIM}Local -> {Fore.YELLOW}{proxy_ip}{Style.RESET_ALL}{Style.DIM} -> {target_domain} ...{Style.RESET_ALL} ({url[:50]}...)")
                except Exception as e:
                    logger.error(f"Error getting next proxy: {e}. Skipping proxy for this attempt.")
                    is_proxy_attempt = False # Fallback to direct if proxy selection fails
                    # Continue to the direct attempt logic below

            # If not a proxy attempt (either disabled, retries exhausted, or error getting proxy)
            if not is_proxy_attempt:
                # Only log direct attempt info once, or if it's the *final* fallback
                if attempt == 0 or (attempt == proxy_retries and use_proxies): # Log if it's the very first try OR the final fallback after proxies
                    log_prefix = f"{log_prefix} (DIRECT)" # Clarify it's a direct attempt
                    logger.info(f"{log_prefix}: {Style.DIM}Local -> DIRECT -> {target_domain}{Style.RESET_ALL} ({url[:50]}...)")
                    final_direct_attempt_made = True # Mark that we made the direct attempt
                elif use_proxies:
                    # This case (attempt > 0 but < proxy_retries and not is_proxy_attempt)
                    # happens if getting a proxy failed mid-cycle. We skip this attempt
                    # to avoid redundant direct tries before the final one.
                    continue

            try:
                response = requests.get(
                    url, headers=self.headers, timeout=20, proxies=proxies_dict # proxies=None if direct
                )

                log_proxy_info = f"{Fore.YELLOW}{urlparse(current_proxy_url).netloc}{Style.RESET_ALL}" if current_proxy_url else "DIRECT"

                if response.status_code >= 400:
                    logger.warning(f"{log_prefix}: {Fore.RED}FAIL{Style.RESET_ALL} (HTTP {response.status_code}) "
                                   f"{Style.DIM}Local -> {log_proxy_info}{Style.DIM} -> {target_domain}{Style.RESET_ALL} ({url[:50]}...)")
                    response.raise_for_status() # Trigger retry/failure

                # Success
                logger.info(f"{log_prefix}: {Fore.GREEN}OK{Style.RESET_ALL} (HTTP {response.status_code}) "
                            f"{Style.DIM}Local -> {log_proxy_info}{Style.DIM} -> {target_domain}{Style.RESET_ALL} ({url[:50]}...)")

                html_content = response.text
                if cache_path:
                    try:
                        with open(cache_path, 'w', encoding='utf-8') as f: f.write(html_content)
                        logger.debug(f"Saved to cache: {cache_path}")
                    except Exception as e: logger.warning(f"Error writing to cache file {cache_path}: {e}")
                return BeautifulSoup(html_content, 'html.parser')

            except requests.exceptions.RequestException as e:
                log_proxy_info = f"{Fore.YELLOW}{urlparse(current_proxy_url).netloc}{Style.RESET_ALL}" if current_proxy_url else "DIRECT"
                logger.warning(f"{log_prefix}: {Fore.RED}FAIL{Style.RESET_ALL} (Network Error) "
                               f"{Style.DIM}Local -> {log_proxy_info}{Style.DIM} -> {target_domain}{Style.RESET_ALL} ({url[:50]}...) - Error: {e}")

                # Check if this was the last possible attempt (either final proxy retry OR the final direct attempt)
                if attempt == total_attempts - 1:
                    logger.error(f"All {total_attempts} attempts failed for {url}.")
                    # Try stale cache as last resort
                    if cache_path and os.path.exists(cache_path):
                        logger.info(f"{Fore.CYAN}CACHE{Style.RESET_ALL}: Using stale cache as final fallback for {url}")
                        try:
                            with open(cache_path, 'r', encoding='utf-8') as f: html_content = f.read()
                            return BeautifulSoup(html_content, 'html.parser')
                        except Exception as read_e: logger.warning(f"Error reading stale cache file {cache_path}: {read_e}")
                    return None # Failed entirely
                # Delay only if we are going to retry (with proxy or direct)
                time.sleep(0.5 if is_proxy_attempt else 0.1) # Shorter delay if falling back to direct

            except Exception as e:
                 logger.error(f"Unexpected error processing {url} (Attempt {attempt+1}): {e}")
                 return None # Unexpected error, stop trying

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