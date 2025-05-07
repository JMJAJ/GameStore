"""
Template for creating a new scraper plugin.
Copy this file and modify it to create a new scraper for a game site.
"""
from .base_scraper import BaseScraper

class TemplateScraper(BaseScraper):
    """
    Template scraper class. Copy and modify this class to create a new scraper.
    """
    
    def __init__(self, base_url="https://example.com", cache_dir=None):
        """
        Initialize the template scraper.
        
        Args:
            base_url (str): The base URL of the site
            cache_dir (str, optional): Directory to cache responses
        """
        super().__init__(base_url, cache_dir)
        
        # REQUIRED: Set these properties for your scraper
        self.site_id = "template"  # Unique identifier for this site, used in URLs
        self.site_name = "Template Site"  # Human-readable name of the site
        
        # OPTIONAL: Additional properties
        self.site_description = "Template scraper for demonstration"  # Description shown in UI
        
    def get_games_list(self, page=1, category=None):
        """
        Get list of games from the site.
        
        Args:
            page (int): Page number
            category (str, optional): Category to filter by
            
        Returns:
            tuple: (games, has_next, categories)
                games (list): List of game dictionaries
                has_next (bool): Whether there's a next page
                categories (list): List of available categories
        """
        # Construct URL based on page and category
        if category:
            url = f"{self.base_url}/category/{category}/page/{page}"
        else:
            url = f"{self.base_url}/page/{page}"
            
        # Get the HTML
        soup = self._get_soup(url)
        
        # Example of parsing game entries
        games = []
        game_elements = soup.select('.game-entry')  # Replace with actual selector
        
        for element in game_elements:
            # Extract information about each game
            title = self._extract_text(element, '.title')
            link = self._extract_link(element, 'a.game-link')
            image = self._extract_image(element, 'img.thumbnail')
            description = self._extract_text(element, '.description', '')
            
            # Add to games list with consistent format
            games.append(self._format_game_data(
                title=title,
                url=link,
                image=image,
                description=description
            ))
        
        # Check if there's a next page
        next_button = soup.select_one('.pagination .next')  # Replace with actual selector
        has_next = next_button is not None
        
        # Get categories if available
        categories = []
        category_elements = soup.select('.categories a')  # Replace with actual selector
        
        for element in category_elements:
            category_name = element.get_text(strip=True)
            category_link = element.get('href', '')
            if category_link:
                # Extract category identifier from URL
                category_id = category_link.split('/')[-1]
                categories.append({
                    'id': category_id,
                    'name': category_name
                })
        
        return games, has_next, categories
    
    def get_game_details(self, url):
        """
        Get detailed information about a game.
        
        Args:
            url (str): URL of the game page
            
        Returns:
            tuple: (meta, description, sysreq, screenshots, downloads, password, related)
                meta (dict): Game metadata
                description (str): Game description
                sysreq (str): System requirements
                screenshots (list): List of screenshot URLs
                downloads (list): List of download links
                password (str): Download password
                related (list): List of related games
        """
        # Get the HTML
        soup = self._get_soup(url)
        
        # Extract metadata
        meta = {
            'title': self._extract_text(soup, '.game-title'),
            'release_date': self._extract_text(soup, '.release-date', None),
            'developer': self._extract_text(soup, '.developer', None),
            'publisher': self._extract_text(soup, '.publisher', None),
            'genres': [g.strip() for g in self._extract_text(soup, '.genres', '').split(',') if g.strip()],
            'image': self._extract_image(soup, '.game-cover'),
            'url': url,
            'site': self.site_id
        }
        
        # Extract description
        description = self._extract_text(soup, '.game-description')
        
        # Extract system requirements
        sysreq = self._extract_text(soup, '.system-requirements')
        
        # Extract screenshots
        screenshots = []
        screenshot_elements = soup.select('.screenshots img')  # Replace with actual selector
        for element in screenshot_elements:
            if element.get('src'):
                screenshot_url = element['src']
                if not screenshot_url.startswith(('http://', 'https://')):
                    screenshot_url = urljoin(self.base_url, screenshot_url)
                screenshots.append(screenshot_url)
        
        # Extract download links
        downloads = []
        download_elements = soup.select('.download-links a')  # Replace with actual selector
        for element in download_elements:
            if element.get('href'):
                link_url = element['href']
                link_text = element.get_text(strip=True)
                downloads.append({
                    'url': link_url,
                    'text': link_text
                })
        
        # Extract password if any
        password = self._extract_text(soup, '.download-password', None)
        
        # Extract related games
        related = []
        related_elements = soup.select('.related-games .game')  # Replace with actual selector
        for element in related_elements:
            title = self._extract_text(element, '.title')
            link = self._extract_link(element, 'a')
            image = self._extract_image(element, 'img')
            
            related.append(self._format_game_data(
                title=title,
                url=link,
                image=image
            ))
        
        return meta, description, sysreq, screenshots, downloads, password, related
    
    def search_games(self, query):
        """
        Search for games.
        
        Args:
            query (str): Search query
            
        Returns:
            list: List of game dictionaries
        """
        # Construct search URL
        search_url = f"{self.base_url}/search?q={query}"
        
        # Get HTML
        soup = self._get_soup(search_url)
        
        # Parse search results
        games = []
        result_elements = soup.select('.search-results .game')  # Replace with actual selector
        
        for element in result_elements:
            title = self._extract_text(element, '.title')
            link = self._extract_link(element, 'a')
            image = self._extract_image(element, 'img')
            description = self._extract_text(element, '.description', '')
            
            games.append(self._format_game_data(
                title=title,
                url=link,
                image=image,
                description=description
            ))
        
        return games 