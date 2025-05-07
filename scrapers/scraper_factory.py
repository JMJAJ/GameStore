"""
Factory for creating scrapers with plugin support.
"""
import os
import logging
import importlib
import pkgutil
from .base_scraper import BaseScraper
from typing import Dict, Type, List, Any, Optional

# Configure logging
logger = logging.getLogger(__name__)

class ScraperFactory:
    """
    Factory for creating scrapers with plugin support.
    This factory automatically discovers and loads scraper plugins.
    """
    
    def __init__(self) -> None:
        """Initialize the factory and discover available scrapers"""
        self.scrapers: Dict[str, Type[BaseScraper]] = {}
        self.site_info: List[Dict[str, str]] = []
        
        self._discover_scrapers()
        
    def _discover_scrapers(self) -> None:
        """
        Discover all available scraper plugins in the package.
        A valid scraper plugin must:
        1. Be a subclass of BaseScraper
        2. Have site_id and site_name attributes
        """
        try:
            # Dynamically import the 'scrapers' package itself to get its path
            package = importlib.import_module('scrapers')
            package_path = package.__path__
        except ImportError:
            logger.error("Could not import the 'scrapers' package. Scraper discovery will fail.")
            return

        for _, name, _ in pkgutil.iter_modules(package_path, package.__name__ + '.'):
            if name.endswith('.base_scraper') or name.endswith('.scraper_factory') or name.endswith('.scraper_template'):
                continue # Skip base, factory, and template modules
                
            try:
                module = importlib.import_module(name)
                for attr_name in dir(module):
                    attr_value = getattr(module, attr_name)
                    
                    if (isinstance(attr_value, type) and
                        issubclass(attr_value, BaseScraper) and
                        attr_value is not BaseScraper):
                        
                        # Use class attributes directly if possible, or instantiate to check
                        site_id = getattr(attr_value, 'site_id', None)
                        site_name_val = getattr(attr_value, 'site_name', None)

                        if not site_id or not site_name_val:
                            # Try instantiating if class attributes are not set (less ideal)
                            try:
                                instance = attr_value()
                                site_id = instance.site_id
                                site_name_val = instance.site_name
                            except Exception: # Catch errors during instantiation for this check
                                logger.debug(f"Could not get site_id/site_name from {attr_name} by instantiation for discovery.")
                                continue # Skip if still no site_id or site_name

                        if site_id and site_name_val:
                            if site_id in self.scrapers:
                                logger.warning(f"Duplicate site_id '{site_id}' found for scraper {attr_name}. Previous: {self.scrapers[site_id].__name__}. Overwriting.")
                            
                            self.scrapers[site_id] = attr_value
                            
                            site_desc = getattr(attr_value, 'site_description', f"Scraper for {site_name_val}")
                            
                            # Remove old entry if site_id is being overwritten
                            self.site_info = [info for info in self.site_info if info['id'] != site_id]
                            
                            self.site_info.append({
                                'id': site_id,
                                'name': site_name_val,
                                'description': site_desc or f"Scraper for {site_name_val}"
                            })
                            logger.info(f"Discovered scraper: {site_id} ({attr_name})")
                        else:
                            logger.debug(f"Scraper class {attr_name} in {name} is missing site_id or site_name class attributes.")
            except ImportError as e:
                logger.warning(f"Failed to import scraper module {name}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error discovering scrapers in module {name}: {e}", exc_info=True)
    
    def get_scraper(self, site_id: str, cache_dir: Optional[str] = None, cache_timeout: Optional[int] = None) -> Optional[BaseScraper]:
        """
        Get an initialized scraper instance for the specified site.

        Args:
            site_id (str): Site identifier.
            cache_dir (str, optional): Directory to cache responses.
            cache_timeout (int, optional): Cache timeout in seconds. If None, BaseScraper default is used.

        Returns:
            Optional[BaseScraper]: A scraper instance for the specified site, or None if not found.

        Raises:
            ValueError: If the site_id is not recognized (though this implementation returns None).
        """
        scraper_class = self.scrapers.get(site_id)
        if scraper_class:
            try:
                if cache_timeout is not None:
                    return scraper_class(cache_dir=cache_dir, cache_timeout=cache_timeout)
                else:
                    # Let BaseScraper use its default timeout if not provided
                    return scraper_class(cache_dir=cache_dir) 
            except Exception as e:
                logger.error(f"Failed to instantiate scraper {scraper_class.__name__} for site_id '{site_id}': {e}")
                return None
        else:
            logger.warning(f"Unknown site_id: {site_id}")
            return None # Changed from raising ValueError to returning None for graceful handling

    def get_all_scrapers(self, cache_dir: Optional[str] = None, cache_timeout: Optional[int] = None) -> Dict[str, BaseScraper]:
        """
        Get all available initialized scraper instances.

        Args:
            cache_dir (str, optional): Directory to cache responses.
            cache_timeout (int, optional): Cache timeout in seconds.

        Returns:
            dict: Dictionary of scraper instances, keyed by site_id.
        """
        initialized_scrapers: Dict[str, BaseScraper] = {}
        for site_id, scraper_class in self.scrapers.items():
            try:
                instance: Optional[BaseScraper]
                if cache_timeout is not None:
                    instance = scraper_class(cache_dir=cache_dir, cache_timeout=cache_timeout)
                else:
                    instance = scraper_class(cache_dir=cache_dir)
                
                if instance:
                    initialized_scrapers[site_id] = instance
            except Exception as e:
                logger.error(f"Failed to instantiate scraper {scraper_class.__name__} for site_id '{site_id}' in get_all_scrapers: {e}")
        return initialized_scrapers


    def get_site_info(self) -> List[Dict[str, str]]:
        """
        Get information about all available sites.

        Returns:
            list: List of site information dictionaries.
        """
        # Sort site_info by name for consistent display
        return sorted(self.site_info, key=lambda x: x['name'])
        
    def register_scraper(self, scraper_class: Type[BaseScraper]) -> bool:
        """
        Register a new scraper class manually.
        Mainly for testing or dynamic loading outside of package discovery.
        
        Args:
            scraper_class: A scraper class (subclass of BaseScraper).
            
        Returns:
            bool: True if registration was successful, False otherwise.
        """
        if not isinstance(scraper_class, type) or not issubclass(scraper_class, BaseScraper):
            logger.warning(f"Cannot register {scraper_class}: not a class or not a subclass of BaseScraper.")
            return False
            
        try:
            # Use class attributes first
            site_id = getattr(scraper_class, 'site_id', None)
            site_name_val = getattr(scraper_class, 'site_name', None)

            if not site_id or not site_name_val: # Fallback to instance if needed
                instance = scraper_class()
                site_id = instance.site_id
                site_name_val = instance.site_name

            if site_id and site_name_val:
                if site_id in self.scrapers:
                    logger.warning(f"Re-registering scraper for site_id '{site_id}'. Overwriting {self.scrapers[site_id].__name__} with {scraper_class.__name__}.")
                
                self.scrapers[site_id] = scraper_class
                
                site_desc = getattr(scraper_class, 'site_description', f"Scraper for {site_name_val}")

                # Update site_info: remove old if exists, then add new
                self.site_info = [info for info in self.site_info if info['id'] != site_id]
                self.site_info.append({
                    'id': site_id,
                    'name': site_name_val,
                    'description': site_desc or f"Scraper for {site_name_val}"
                })
                logger.info(f"Manually registered scraper: {site_id} ({scraper_class.__name__})")
                return True
            else:
                logger.warning(f"Cannot register {scraper_class.__name__}: missing site_id or site_name attributes.")
                return False
        except Exception as e:
            logger.error(f"Failed to initialize or get attributes from scraper {scraper_class.__name__} for manual registration: {e}")
            return False