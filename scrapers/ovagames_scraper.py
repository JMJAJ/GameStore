"""
OvaGames scraper for the GameStore application.
"""
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

    def get_games_list(self, page: int = 1, category: Optional[str] = None) -> Tuple[List[Dict[str, Any]], bool, List[Dict[str, str]]]:
        # --- This seemed to be working, keeping it the same ---
        if not self.base_url:
            logger.error("OvaGamesScraper: base_url is not set.")
            return [], False, []

        if category:
            url = f"{self.base_url}/category/{quote(category)}/page/{page}"
        else:
            url = f"{self.base_url}/page/{page}"

        soup: Optional[BeautifulSoup] = self._get_soup(url)
        if not soup:
            logger.warning(f"Failed to get soup object for URL: {url}")
            return [], False, []

        games: List[Dict[str, Any]] = []
        for game_entry_el in soup.select("div.home-post-wrap"):
            link_el = game_entry_el.select_one(".home-post-titles h2 a")
            if not link_el or not link_el.get('href'):
                logger.debug("Skipping game entry, link not found.")
                continue
            game_url = self._normalize_url(link_el['href'])
            if not game_url: continue
            title = link_el.get_text(strip=True) or "Unknown Title"
            img_el = game_entry_el.select_one(".post-inside a img.thumbnail")
            image_url: Optional[str] = None
            if img_el:
                src_candidate = img_el.get('src') or img_el.get('data-src')
                if src_candidate: image_url = self._normalize_url(src_candidate)
            games.append(self._format_game_data(title=title, url=game_url, image=image_url, release_date=None))

        next_link_el = soup.select_one("div.wp-pagenavi a.nextpostslink")
        has_next = bool(next_link_el and next_link_el.get('href'))
        if not games and page > 1: has_next = False
        logger.info(f"Games found: {len(games)}, Has next page: {has_next}")

        categories: List[Dict[str, str]] = []
        category_elements = soup.select("ul#menu-2nd li.menu-item-object-category a, .sidebar .widget_categories ul li a, .sidebar #categories-3 ul li a")
        logger.info(f"Found {len(category_elements)} potential category elements.")
        for cat_el in category_elements:
            cat_name = cat_el.get_text(strip=True)
            cat_href = self._normalize_url(cat_el.get('href'))
            if cat_name and cat_href:
                path_parts = urlparse(cat_href).path.strip('/').split('/')
                slug = ""
                if len(path_parts) > 0:
                    if path_parts[0] == 'category' and len(path_parts) > 1: slug = path_parts[-1]
                    elif path_parts[0] != 'category': slug = path_parts[-1]
                if slug: categories.append({"name": cat_name, "slug": slug})

        if categories:
            unique_categories_dict = {item['slug'].lower(): item for item in categories}
            categories = sorted(list(unique_categories_dict.values()), key=lambda x: x['name'])
        logger.info(f"Processed {len(categories)} unique categories.")

        return games, has_next, categories


    def get_game_details(self, url: str) -> Tuple[Dict[str, Any], Optional[str], Optional[str], List[str], List[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
        logger.info(f"Getting game details for: {url}")
        soup: Optional[BeautifulSoup] = self._get_soup(url)
        if not soup: return {}, None, None, [], [], None, []

        content_area = soup.select_one("div.post-wrapper, div.post-content, div.entry-content, article.single-post")
        if not content_area:
             content_area = soup.body if soup.body else soup
             if not content_area: return {}, None, None, [], [], None, []

        meta: Dict[str, Any] = {
            "title": self._extract_text(content_area, "h1.post-title, h1.entry-title", "Unknown Game"),
            "url": url, "site": self.site_id }
        logger.debug(f"Extracted Title: {meta['title']}")

        # --- Metadata Extraction ---
        info_text_blob: str = ""
        potential_info_sources = content_area.find_all(['p', 'div'], recursive=False, limit=10)
        if not potential_info_sources: potential_info_sources = content_area.find_all(['p', 'div'], limit=15)
        for source_el in potential_info_sources:
            p_text = source_el.get_text(" ", strip=True)
            if re.search(r'(Title|Genre|Developer|Publisher|Release Date)\s*:', p_text, re.IGNORECASE): info_text_blob += p_text + "\n"
            if source_el.find(['h2', 'h3', 'div.wp-tabs', 'div.gallery', 'div.download-links']):
                 if info_text_blob: break
        logger.debug(f"Extracted Info Blob:\n{info_text_blob}")
        def extract_from_blob(label: str, text_blob: str) -> Optional[str]:
            match = re.search(rf"{label}\s*:?\s*(.*?)(?:\n|\r|Release Date:|Genre:|Developer:|Publisher:|$)", text_blob, re.IGNORECASE | re.DOTALL)
            value = match.group(1).strip().replace('<br>', '').replace('<br/>', '') if match and match.group(1).strip() else None
            if value and ':' in value and not any(l+':' in value for l in ['http', 'https']): value = value.split(':')[0].strip()
            return value
        meta["genre"] = extract_from_blob("Genre", info_text_blob)
        meta["developer"] = extract_from_blob("Developer", info_text_blob)
        meta["publisher"] = extract_from_blob("Publisher", info_text_blob)
        meta["release_date"] = extract_from_blob("Release Date", info_text_blob)
        logger.debug(f"Extracted Meta: Genre={meta['genre']}, Dev={meta['developer']}, Pub={meta['publisher']}, Date={meta['release_date']}")

        # --- Cover Image ---
        img_el = content_area.select_one("p > a > img, p > img, figure > img, .separator > a > img, .separator > img")
        if img_el:
            src_candidate = img_el.get('data-src') or img_el.get('src')
            if src_candidate: meta["image"] = self._normalize_url(src_candidate)
        logger.debug(f"Cover Image: {meta.get('image', 'Not Found')}")

        # --- Initialize variables ---
        description: Optional[str] = None
        sysreq: Optional[str] = None
        screenshots: List[str] = []
        downloads: List[Dict[str, Any]] = []
        password: Optional[str] = None
        related_games: List[Dict[str, Any]] = []

        # --- Tab Content Extraction (Revised) ---
        tab_container = soup.select_one("div.wp-tabs, div.tabs-container, div#tabs")

        if tab_container:
            logger.debug("Tab container found. Processing tabs...")
            # Find panels based on the common structure seen in 'Clair Obscur'
            desc_panel = tab_container.select_one("#description .wp-tab-content-wrapper")
            sysreq_panel = tab_container.select_one("#system_requirements .wp-tab-content-wrapper")
            screenshot_panel = tab_container.select_one("#screenshot .wp-tab-content-wrapper")
            download_panel = tab_container.select_one("#link_download .wp-tab-content-wrapper")

            if desc_panel:
                description = desc_panel.get_text("\n", strip=True)
                logger.debug("Found description via specific tab selector.")
            if sysreq_panel:
                sysreq = sysreq_panel.get_text("\n", strip=True)
                logger.debug("Found system requirements via specific tab selector.")
            if screenshot_panel:
                logger.debug("Processing screenshot tab panel...")
                # Images are often directly inside img tags here
                for img_el in screenshot_panel.select("img"): # Simpler selector for direct images
                    src_candidate = img_el.get('data-src') or img_el.get('src')
                    if src_candidate:
                        full_src = self._normalize_url(src_candidate)
                        if full_src and full_src not in screenshots and full_src != meta.get("image"):
                            screenshots.append(full_src)
                logger.debug(f"Found {len(screenshots)} screenshots in tab.")
            if download_panel:
                logger.debug("Processing download tab panel...")
                # Password check first
                pwd_box = download_panel.select_one("div.su-box-content")
                if pwd_box:
                    pwd_text_content = pwd_box.get_text(" ", strip=True)
                    # Look for "Rar password:" specifically
                    pwd_match = re.search(r"Rar password\s*:\s*([\w.-]+)", pwd_text_content, re.IGNORECASE)
                    if pwd_match: password = pwd_match.group(1)
                    else: # Fallback regex if specific label not found
                        pwd_match = re.search(r"Password\s*:?\s*([\w.-]+)", pwd_text_content, re.IGNORECASE)
                        if pwd_match: password = pwd_match.group(1)

                # Download links using '.dl-wraps-item' structure
                for item_div in download_panel.select(".dl-wraps-item"):
                    section_title_tag = item_div.find('b')
                    section_title = section_title_tag.get_text(strip=True) if section_title_tag else "Download Links"
                    group = "Update" if "UPDATE" in section_title.upper() else "Main Game"
                    # Links are usually inside <p><a>...</a><br><a>...</a></p>
                    for link_el in item_div.select("p a[href]"): # Target links within paragraphs inside the item
                        href_raw = link_el.get('href')
                        text = link_el.get_text(strip=True) or "Download" # Host name is the link text
                        if href_raw and not href_raw.strip().startswith(('javascript:', '#')):
                            href = self._normalize_url(href_raw)
                            if href and not any(d['url'] == href for d in downloads):
                                downloads.append({"url": href, "text": text, "group": group, "section": section_title})
                logger.debug(f"Found {len(downloads)} download links in tab. Password found: {'Yes' if password else 'No'}")

        # --- Fallback Logic (if tabs didn't provide full info) ---
        if not description or not sysreq or not downloads or not screenshots:
            logger.info("Tab extraction incomplete or tabs not found, using header/content flow fallback.")
            all_headers = content_area.find_all(['h2', 'h3', 'h4', 'strong', 'b'], recursive=True)
            desc_start_node, sysreq_start_node, screenshots_start_node, download_start_node = None, None, None, None
            for header in all_headers:
                txt = header.get_text(strip=True).lower()
                if not desc_start_node and 'description' in txt: desc_start_node = header
                if not sysreq_start_node and ('system requirements' in txt or ('minimum' in txt and 'recommended' in txt)): sysreq_start_node = header
                if not screenshots_start_node and 'screenshot' in txt: screenshots_start_node = header
                if not download_start_node and ('download' in txt or 'link' in txt): download_start_node = header
            def extract_between(start_node, end_node):
                # ... (existing extract_between logic) ...
                if not start_node: return None
                parts = []
                curr = start_node.next_sibling
                while curr and curr != end_node:
                    if isinstance(curr, Tag) and curr.name in ['p', 'ul', 'div', 'li', 'pre']:
                         txt = curr.get_text("\n", strip=True); parts.append(txt)
                    elif not isinstance(curr, Tag) and curr.strip(): parts.append(curr.strip())
                    curr = curr.next_sibling
                return "\n".join(filter(None, parts)).strip() or None
            if not description:
                end = sysreq_start_node or screenshots_start_node or download_start_node
                description = extract_between(desc_start_node or info_text_blob and content_area.find('p', string=re.compile(info_text_blob.split('\n')[-1])), end)
                if description: logger.debug("Extracted description via header/flow fallback.")
            if not sysreq:
                end = screenshots_start_node or download_start_node
                sysreq = extract_between(sysreq_start_node, end)
                if sysreq: logger.debug("Extracted system reqs via header/flow fallback.")
            if not screenshots:
                 logger.debug("Attempting screenshot extraction via header/flow fallback.")
                 # Look for images between screenshot header and download header
                 area_to_search = content_area # Default to whole content
                 if screenshots_start_node:
                      temp_soup_str = ""
                      curr = screenshots_start_node.next_sibling
                      while curr and curr != download_start_node:
                          if isinstance(curr, Tag): temp_soup_str += str(curr)
                          curr = curr.next_sibling
                      if temp_soup_str: area_to_search = BeautifulSoup(f"<div>{temp_soup_str}</div>", "html.parser")

                 for img_el in area_to_search.select("img"):
                     src = img_el.get('src') or img_el.get('data-src')
                     if src:
                         full_src = self._normalize_url(src)
                         if full_src and full_src != meta.get("image") and not any(kw in full_src for kw in ['icon', 'logo', 'button', 'feed', 'spinner']):
                            if full_src not in screenshots: screenshots.append(full_src)
                 if screenshots: logger.debug(f"Found {len(screenshots)} screenshots via fallback.")

            if not downloads:
                 logger.debug("Attempting download extraction via header/flow fallback.")
                 area_to_search = content_area
                 if download_start_node:
                      temp_soup_str = ""
                      curr = download_start_node.next_sibling
                      while curr: # Go to end or next h2/h3
                          if isinstance(curr, Tag) and curr.name in ['h2', 'h3']: break
                          if isinstance(curr, Tag): temp_soup_str += str(curr)
                          curr = curr.next_sibling
                      if temp_soup_str: area_to_search = BeautifulSoup(f"<div>{temp_soup_str}</div>", "html.parser")

                 # Reuse simpler link finding logic from tab fallback
                 for link_el in area_to_search.select(".dl-wraps-item a, .download-links a, .su-button-center a, a[href*='zippyshare'], a[href*='mega.nz'], a[href*='1fichier'], a[href*='uptobox']"):
                     href = self._normalize_url(link_el.get('href'))
                     text = link_el.get_text(strip=True) or "Download"
                     if href and not any(d['url'] == href for d in downloads):
                         downloads.append({"url": href, "text": text, "group": "Downloads", "section": "Links"})
                 if downloads: logger.debug(f"Found {len(downloads)} downloads via fallback.")
                 # Fallback password check
                 if not password:
                     pwd_box = area_to_search.select_one("div.su-box-content, .password-box, div[class*='password']")
                     if pwd_box:
                         pwd_match = re.search(r"Password\s*:?\s*([\w.-]+)", pwd_box.get_text(" ", strip=True), re.IGNORECASE)
                         if pwd_match: password = pwd_match.group(1)
                     if not password: # Final check in whole area text
                          pwd_match = re.search(r"Password\s*:?\s*([\w.-]+)", area_to_search.get_text(" ", strip=True), re.IGNORECASE)
                          if pwd_match: password = pwd_match.group(1)
                     if password: logger.debug("Found password via fallback.")

        # --- Related Games ---
        related_games: List[Dict[str, Any]] = []
        related_container = soup.select_one(".related-posts, #yarpp_widget-, .rp4wp-related-posts, div[id*='related']")
        if related_container:
            logger.debug("Related posts container found.")
            for link_el in related_container.select("a[href]"):
                 related_url_raw = link_el.get('href')
                 if not related_url_raw or related_url_raw == url or not re.search(r'/[a-zA-Z0-9-]+/?$', related_url_raw): continue
                 related_url = self._normalize_url(related_url_raw)
                 if not related_url: continue
                 related_title = link_el.get_text(strip=True)
                 img_tag = link_el.find("img")
                 related_image = None
                 if img_tag:
                     img_src_candidate = img_tag.get('data-src') or img_tag.get('src')
                     if img_src_candidate: related_image = self._normalize_url(img_src_candidate)
                 if not related_title and img_tag and img_tag.get('alt'): related_title = img_tag.get('alt', '')
                 if not related_title: related_title = related_url.strip('/').split('/')[-1].replace('-', ' ').title()
                 if related_title and related_title.lower() != meta["title"].lower():
                     if not any(g['url'] == related_url for g in related_games):
                         related_games.append(self._format_game_data(title=related_title, url=related_url, image=related_image))
                 if len(related_games) >= 6: break
        logger.info(f"Found {len(related_games)} related games.")

        return meta, description, sysreq, screenshots, downloads, password, related_games


    def search_games(self, query: str) -> List[Dict[str, Any]]:
        # --- This seemed to be working, keeping it the same ---
        if not self.base_url: return []
        search_url = f"{self.base_url}/?s={quote(query)}"
        logger.info(f"Searching OvaGames with URL: {search_url}")
        soup: Optional[BeautifulSoup] = self._get_soup(search_url)
        if not soup: return []

        games: List[Dict[str, Any]] = []
        for game_entry_el in soup.select("div.home-post-wrap"):
            link_el = game_entry_el.select_one(".home-post-titles h2 a")
            if not link_el or not link_el.get('href'): continue
            game_url = self._normalize_url(link_el['href'])
            if not game_url: continue
            title = link_el.get_text(strip=True) or "Unknown Title"
            img_el = game_entry_el.select_one(".post-inside a img.thumbnail")
            image_url: Optional[str] = None
            if img_el:
                src_candidate = img_el.get('src') or img_el.get('data-src')
                if src_candidate: image_url = self._normalize_url(src_candidate)
            games.append(self._format_game_data(title=title, url=game_url, image=image_url))
            if len(games) >= 20: break
        logger.info(f"Found {len(games)} results for search query: '{query}'")
        return games