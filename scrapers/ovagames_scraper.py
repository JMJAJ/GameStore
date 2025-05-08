# scrapers/ovagames_scraper.py

import re
import logging
from urllib.parse import urljoin, quote, urlparse
from bs4 import BeautifulSoup, Tag
from .base_scraper import BaseScraper
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class OvaGamesScraper(BaseScraper):
    site_id: str = "ovagames"
    site_name: str = "OvaGames"
    site_description: str = "A popular site for PC games"
    base_url: str = "https://ovagames.com"

    def __init__(self, base_url_override: Optional[str] = None,
                 cache_dir: Optional[str] = None,
                 cache_timeout: int = 3600):
        effective_base_url = base_url_override or self.base_url
        super().__init__(effective_base_url, cache_dir, cache_timeout)

    # --- get_games_list remains unchanged ---
    def get_games_list(self, page: int = 1, category: Optional[str] = None) -> Tuple[List[Dict[str, Any]], bool, List[Dict[str, str]]]:
        if not self.base_url: logger.error("OvaGamesScraper: base_url is not set."); return [], False, []
        if category: url = f"{self.base_url}/category/{quote(category)}/page/{page}"
        else: url = f"{self.base_url}/page/{page}"
        soup: Optional[BeautifulSoup] = self._get_soup(url)
        if not soup: logger.warning(f"Failed to get soup object for URL: {url}"); return [], False, []
        games: List[Dict[str, Any]] = []
        for game_entry_el in soup.select("div.home-post-wrap"):
            link_el = game_entry_el.select_one(".home-post-titles h2 a")
            if not link_el or not link_el.get('href'): continue
            game_url = self._normalize_url(link_el['href'])
            if not game_url: continue
            title = link_el.get_text(strip=True) or "Unknown Title"
            img_el = game_entry_el.select_one(".post-inside a img.thumbnail")
            image_url: Optional[str] = None
            if img_el: src_candidate = img_el.get('src') or img_el.get('data-src'); image_url = self._normalize_url(src_candidate) if src_candidate else None
            games.append(self._format_game_data(title=title, url=game_url, image=image_url, release_date=None))
        next_link_el = soup.select_one("div.wp-pagenavi a.nextpostslink"); has_next = bool(next_link_el and next_link_el.get('href'))
        if not games and page > 1: has_next = False; logger.info(f"Games found: {len(games)}, Has next page: {has_next}")
        categories: List[Dict[str, str]] = []
        category_elements = soup.select("ul#menu-2nd li.menu-item-object-category a, .sidebar .widget_categories ul li a, .sidebar #categories-3 ul li a")
        logger.info(f"Found {len(category_elements)} potential category elements.")
        for cat_el in category_elements:
            cat_name = cat_el.get_text(strip=True); cat_href = self._normalize_url(cat_el.get('href'))
            if cat_name and cat_href: path_parts = urlparse(cat_href).path.strip('/').split('/'); slug = path_parts[-1] if len(path_parts)>0 and (path_parts[0]=='category' or len(path_parts)==1) else None; categories.append({"name": cat_name, "slug": slug}) if slug else None
        if categories: unique_categories_dict = {item['slug'].lower(): item for item in categories}; categories = sorted(list(unique_categories_dict.values()), key=lambda x: x['name'])
        logger.info(f"Processed {len(categories)} unique categories."); return games, has_next, categories

    def get_game_details(self, url: str) -> Tuple[Dict[str, Any], Optional[str], Optional[str], List[str], List[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
        logger.info(f"Getting game details for: {url}")
        soup: Optional[BeautifulSoup] = self._get_soup(url)
        if not soup: return {}, None, None, [], [], None, []

        content_area = soup.select_one("div.post-wrapper, div.post-content, div.entry-content, article.single-post")
        if not content_area: content_area = soup.body if soup.body else soup
        if not content_area: return {}, None, None, [], [], None, []

        meta: Dict[str, Any] = {"url": url, "site": self.site_id}
        meta["title"] = self._extract_text(content_area, "h1.post-title, h1.entry-title", "Unknown Game"); logger.debug(f"Extracted Title: {meta['title']}")

        # --- Metadata ---
        info_text_blob: str = ""
        potential_info_sources = content_area.find_all(['p', 'div'], recursive=False, limit=10)
        if not potential_info_sources: potential_info_sources = content_area.find_all(['p', 'div'], limit=15)
        for source_el in potential_info_sources:
            p_text = source_el.get_text(" ", strip=True)
            if re.search(r'(Title|Genre|Developer|Publisher|Release Date|Mirrors|File Size)\s*:', p_text, re.I): info_text_blob += p_text + "\n"
            if source_el.find(['h2', 'h3', 'div.wp-tabs', 'div.gallery', 'div.download-links']):
                 if info_text_blob: break
        logger.debug(f"Extracted Info Blob:\n{info_text_blob}")
        def extract_from_blob(label: str, text_blob: str) -> Optional[str]:
            match = re.search(rf"{label}\s*:?\s*(.*?)(?:\n|\r|Release Date:|Genre:|Developer:|Publisher:|Mirrors:|File Size:|$)", text_blob, re.I | re.S) # Use DOTALL
            value = match.group(1).strip().replace('<br>', '').replace('<br/>', '') if match and match.group(1).strip() else None
            if value and ':' in value and not any(l+':' in value for l in ['http', 'https']): value = value.split(':')[0].strip()
            return value
        meta["genre"] = extract_from_blob("Genre", info_text_blob)
        meta["developer"] = extract_from_blob("Developer", info_text_blob)
        meta["publisher"] = extract_from_blob("Publisher", info_text_blob)
        meta["release_date"] = extract_from_blob("Release Date", info_text_blob)
        # Add File Size and Mirrors if present in the blob
        meta["file_size"] = extract_from_blob("File Size", info_text_blob)
        meta["mirrors_text"] = extract_from_blob("Mirrors", info_text_blob) # Store raw text for now
        logger.debug(f"Extracted Meta: Genre={meta['genre']}, Dev={meta['developer']}, Pub={meta['publisher']}, Date={meta['release_date']}, Size={meta['file_size']}, Mirrors={meta['mirrors_text']}")

        # --- Cover Image ---
        img_el = content_area.select_one("p > a > img, p > img, figure > img, .separator > a > img, .separator > img")
        if img_el: src_candidate = img_el.get('data-src') or img_el.get('src'); meta["image"] = self._normalize_url(src_candidate) if src_candidate else None
        logger.debug(f"Cover Image: {meta.get('image', 'Not Found')}")

        # --- Initialize ---
        description: Optional[str] = None; sysreq: Optional[str] = None
        screenshots: List[str] = []; downloads: List[Dict[str, Any]] = []
        password: Optional[str] = None; related_games: List[Dict[str, Any]] = []

        # --- Try Tab Extraction First ---
        tab_container = soup.select_one("div.wp-tabs, div.tabs-container, div#tabs")
        if tab_container:
            logger.debug("Tab container found. Processing tabs...")
            desc_panel = tab_container.select_one("#description .wp-tab-content-wrapper"); sysreq_panel = tab_container.select_one("#system_requirements .wp-tab-content-wrapper")
            screenshot_panel = tab_container.select_one("#screenshot .wp-tab-content-wrapper"); download_panel = tab_container.select_one("#link_download .wp-tab-content-wrapper")
            if desc_panel: description = desc_panel.get_text("\n", strip=True); logger.debug("Found description in tab.")
            if sysreq_panel: sysreq = sysreq_panel.get_text("\n", strip=True); logger.debug("Found sysreq in tab.")
            if screenshot_panel:
                 for img_el in screenshot_panel.select("img"): src = img_el.get('data-src') or img_el.get('src'); full_src = self._normalize_url(src); screenshots.append(full_src) if full_src and full_src not in screenshots and full_src != meta.get("image") else None
                 logger.debug(f"Found {len(screenshots)} screenshots in tab.")
            if download_panel:
                 pwd_box = download_panel.select_one("div.su-box-content");
                 if pwd_box: pwd_text = pwd_box.get_text(" ",strip=True); pwd_match = re.search(r"(?:Rar |Filecrypt folder )?password\s*:?\s*([\w\.-]+)", pwd_text, re.I); password = pwd_match.group(1) if pwd_match else None
                 for item_div in download_panel.select(".dl-wraps-item"):
                     title_tag = item_div.find('b'); title_text = title_tag.get_text(strip=True) if title_tag else "Links"; group = "Update" if "UPDATE" in title_text.upper() else "Main Game"
                     for link_el in item_div.select("p a[href]"): href = self._normalize_url(link_el.get('href')); text = link_el.get_text(strip=True) or "Download"; downloads.append({"url": href, "text": text, "group": group, "section": title_text}) if href and not any(d['url'] == href for d in downloads) else None
                 logger.debug(f"Found {len(downloads)} downloads in tab. Password: {'Yes' if password else 'No'}")

        # --- Fallback/Combined Logic (If tabs missing or need more) ---
        if not description or not sysreq or not downloads or not screenshots:
            logger.info("Tab extraction incomplete or tabs not found, using content flow fallback.")
            # Find potential section start nodes based on H2/H3/Strong tags
            headers = content_area.find_all(['h2', 'h3', 'strong', 'b'], recursive=True)
            desc_start, sysreq_start, screen_start, dl_start, install_start = None, None, None, None, None
            for h in headers:
                txt = h.get_text(strip=True).lower()
                if not desc_start and 'description' in txt: desc_start = h
                elif not sysreq_start and ('system requirements' in txt or ('minimum' in txt and 'recommended' in txt)): sysreq_start = h
                elif not screen_start and 'screenshot' in txt: screen_start = h
                elif not dl_start and ('link download' in txt or 'download links' in txt or 'download link' in txt): dl_start = h
                elif not install_start and 'install note' in txt: install_start = h

            # Define end markers for extraction
            desc_end = sysreq_start or screen_start or dl_start or install_start
            sysreq_end = screen_start or dl_start or install_start
            screen_end = dl_start or install_start
            dl_end = install_start

            # Helper to extract text between nodes
            def extract_between(start_node, end_node, include_tags=['p', 'ul', 'div', 'li', 'pre']):
                if not start_node: return None
                parts = []
                curr = start_node.next_sibling
                while curr and curr != end_node:
                    if isinstance(curr, Tag) and curr.name in include_tags: parts.append(curr.get_text("\n", strip=True))
                    elif not isinstance(curr, Tag) and curr.strip(): parts.append(curr.strip())
                    curr = curr.next_sibling
                return "\n".join(filter(None, parts)).strip() or None

            # Extract Description (if not found in tab)
            if not description:
                start = desc_start or content_area.find('p', string=re.compile(r'free download.*repack pc game', re.I)) # Start after intro para
                description = extract_between(start, desc_end)
                if description: logger.debug("Extracted description via fallback.")

            # Extract System Requirements (if not found in tab)
            if not sysreq:
                sysreq = extract_between(sysreq_start, sysreq_end)
                # Special case for Car Demo: SysReq text might contain links. Extract pure text.
                if sysreq_start:
                    sysreq_content = []
                    curr = sysreq_start.next_sibling
                    while curr and curr != sysreq_end:
                        if isinstance(curr, Tag) and curr.name in ['p', 'ul', 'div', 'li']:
                             # Get text but exclude the download link text if present
                             temp_text = ""
                             for item in curr.contents:
                                 if isinstance(item, Tag) and item.name == 'a' and item.get('href'):
                                     continue # Skip link tags
                                 temp_text += item.get_text(" ", strip=True) if isinstance(item, Tag) else str(item)
                             if temp_text.strip(): sysreq_content.append(temp_text.strip())
                        elif not isinstance(curr, Tag) and curr.strip():
                            sysreq_content.append(curr.strip())
                        curr = curr.next_sibling
                    sysreq = "\n".join(sysreq_content).strip() or sysreq # Overwrite if found this way

                if sysreq: logger.debug("Extracted system reqs via fallback.")

            # Extract Screenshots (if not found in tab)
            if not screenshots:
                area = content_area
                if screen_start: # Limit search area if header found
                    temp_soup_str = ""; curr = screen_start.next_sibling
                    while curr and curr != screen_end: temp_soup_str += str(curr) if isinstance(curr, Tag) else ''; curr = curr.next_sibling
                    if temp_soup_str: area = BeautifulSoup(f"<div>{temp_soup_str}</div>", "html.parser")
                for img_el in area.select("img.aligncenter, a[href*='.jpg'] > img, a[href*='.png'] > img"): # Look for common patterns
                     src = img_el.get('src') or img_el.get('data-src') or (img_el.parent.name == 'a' and img_el.parent.get('href'))
                     if src: full_src = self._normalize_url(src); screenshots.append(full_src) if full_src and full_src not in screenshots and full_src != meta.get("image") else None
                if screenshots: logger.debug(f"Found {len(screenshots)} screenshots via fallback.")

            # Extract Downloads (if not found in tab)
            if not downloads:
                 area = content_area
                 if dl_start: # Limit search area
                      temp_soup_str = ""; curr = dl_start.next_sibling
                      while curr and curr != dl_end: temp_soup_str += str(curr) if isinstance(curr, Tag) else ''; curr = curr.next_sibling
                      if temp_soup_str: area = BeautifulSoup(f"<div>{temp_soup_str}</div>", "html.parser")
                 # Look for common host links directly in paragraphs or list items
                 for link_el in area.select("p > a[href], li > a[href]"):
                     href = self._normalize_url(link_el.get('href'))
                     # Check if previous sibling text looks like a host name (e.g., ✓ MEGA)
                     prev_sib = link_el.find_previous_sibling(string=True)
                     text = link_el.get_text(strip=True) or (prev_sib.strip().lstrip('✓').strip() if prev_sib else "Download")

                     # Filter out common non-download links often found here
                     if href and not any(kw in href for kw in ['#comments', '/faq', '/category/', '/author/']) and not any(d['url'] == href for d in downloads):
                         downloads.append({"url": href, "text": text, "group": "Downloads", "section": "Links"})
                 if downloads: logger.debug(f"Found {len(downloads)} downloads via fallback.")

            # Extract Password (if not found in tab) - search whole content area
            if not password:
                 pwd_box = content_area.select_one("div.su-box-content, .password-box, div[class*='password'], blockquote")
                 if pwd_box: pwd_match = re.search(r"Password\s*:?\s*([\w.-]+)", pwd_box.get_text(" ", strip=True), re.I); password = pwd_match.group(1) if pwd_match else None
                 if not password: pwd_match = re.search(r"Password\s*:?\s*([\w.-]+)", content_area.get_text(" ", strip=True), re.I); password = pwd_match.group(1) if pwd_match else None
                 if password: logger.debug("Found password via fallback.")

        # --- Related Games ---
        # ... (unchanged) ...
        related_games: List[Dict[str, Any]] = []; related_container = soup.select_one(".related-posts, #yarpp_widget-, .rp4wp-related-posts, div[id*='related']")
        if related_container:
            logger.debug("Related posts container found.")
            for link_el in related_container.select("a[href]"):
                 related_url_raw = link_el.get('href')
                 if not related_url_raw or related_url_raw == url or not re.search(r'/[a-zA-Z0-9-]+/?$', related_url_raw): continue
                 related_url = self._normalize_url(related_url_raw);
                 if not related_url: continue
                 related_title = link_el.get_text(strip=True); img_tag = link_el.find("img"); related_image = None
                 if img_tag: img_src_candidate = img_tag.get('data-src') or img_tag.get('src'); related_image = self._normalize_url(img_src_candidate) if img_src_candidate else None
                 if not related_title and img_tag and img_tag.get('alt'): related_title = img_tag.get('alt', '')
                 if not related_title: related_title = related_url.strip('/').split('/')[-1].replace('-', ' ').title()
                 if related_title and related_title.lower() != meta["title"].lower():
                     if not any(g['url'] == related_url for g in related_games): related_games.append(self._format_game_data(title=related_title, url=related_url, image=related_image))
                 if len(related_games) >= 6: break
        logger.info(f"Found {len(related_games)} related games.")

        return meta, description, sysreq, screenshots, downloads, password, related_games

    def search_games(self, query: str) -> List[Dict[str, Any]]:
        # ... (unchanged) ...
        if not self.base_url: return []
        search_url = f"{self.base_url}/?s={quote(query)}"; logger.info(f"Searching OvaGames with URL: {search_url}")
        soup: Optional[BeautifulSoup] = self._get_soup(search_url);
        if not soup: return []
        games: List[Dict[str, Any]] = []
        for game_entry_el in soup.select("div.home-post-wrap"):
            link_el = game_entry_el.select_one(".home-post-titles h2 a");
            if not link_el or not link_el.get('href'): continue
            game_url = self._normalize_url(link_el['href']);
            if not game_url: continue
            title = link_el.get_text(strip=True) or "Unknown Title"; img_el = game_entry_el.select_one(".post-inside a img.thumbnail"); image_url: Optional[str] = None
            if img_el: src_candidate = img_el.get('src') or img_el.get('data-src'); image_url = self._normalize_url(src_candidate) if src_candidate else None
            games.append(self._format_game_data(title=title, url=game_url, image=image_url))
            if len(games) >= 20: break
        logger.info(f"Found {len(games)} results for search query: '{query}'"); return games