"""
GamePCISO scraper for the GameStore application.
"""
import re
import logging
from urllib.parse import urljoin, quote, urlparse
from bs4 import BeautifulSoup, Tag
from .base_scraper import BaseScraper
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class GamePCISOScraper(BaseScraper):
    site_id: str = "gamepciso"
    site_name: str = "GamePCISO"
    site_description: str = "Game PC ISO download site"
    base_url: str = "https://gamepciso.com"

    def __init__(self, base_url_override: Optional[str] = None,
                 cache_dir: Optional[str] = None,
                 cache_timeout: int = 3600):
        effective_base_url = base_url_override or self.base_url
        super().__init__(effective_base_url, cache_dir, cache_timeout)

    def _clean_title(self, title: str) -> str:
        # ... (unchanged) ...
        if not title: return "Unknown Title"
        title = re.sub(r'\s*-\s*Download Game PC Iso New Free$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*Download\s+Free\s*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*Free\s+Download\s*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*PC\s+Game\s+Free\s*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*PC\s+Game\s*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*Full\s+Version\s*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*Repack\s*$', '', title, flags=re.IGNORECASE)
        return title.strip()

    def _resolve_image_url(self, img_url: Optional[str], base_page_url: Optional[str] = None) -> Optional[str]:
        # ... (unchanged) ...
        if not img_url: return None
        full_url = self._normalize_url(img_url, base_page_url or self.base_url)
        if not full_url: return None
        match = re.search(r'/(s\d+(-[cp])?|w\d+-h\d+(-[cpkno]+)?)/', full_url)
        if match: return full_url.replace(match.group(1), "s1600")
        if full_url.startswith('data:'): return full_url
        return full_url

    def get_games_list(self, page: int = 1, category: Optional[str] = None) -> Tuple[List[Dict[str, Any]], bool, List[Dict[str, str]]]:
        # ... (unchanged from previous fix, seems stable) ...
        if not self.base_url:
            logger.error(f"{self.site_name}: base_url is not set.")
            return [], False, []
        if category:
            safe_category = quote(category)
            if page > 1: url = f"{self.base_url}/category/{safe_category}/page/{page}/"
            else: url = f"{self.base_url}/category/{safe_category}/"
        else:
             if page > 1: url = f"{self.base_url}/page/{page}/"
             else: url = self.base_url + "/"

        logger.info(f"Fetching game list from: {url}")
        soup: Optional[BeautifulSoup] = self._get_soup(url)
        if not soup: return [], False, []

        games: List[Dict[str, Any]] = []
        for game_el in soup.select("div.post.bar.hentry"):
            link_el = game_el.select_one("h2.post-title.entry-title a")
            if not link_el or not link_el.get('href'): continue
            game_url = self._normalize_url(link_el['href'])
            if not game_url: continue
            cleaned_title = self._clean_title(link_el.get_text(strip=True))
            img_el = game_el.select_one(".post-body div[id^='summary'] img, .post-body img")
            image_url: Optional[str] = None
            if img_el:
                src_candidate = img_el.get('data-src') or img_el.get('src') or img_el.get('data-lazy-src')
                if src_candidate: image_url = self._resolve_image_url(src_candidate, game_url)
            release_date = None
            date_el = game_el.select_one(".postmeta .date, .entry-date, time.published")
            if date_el: release_date = date_el.get_text(strip=True) or date_el.get('datetime')
            games.append(self._format_game_data(title=cleaned_title, url=game_url, image=image_url, release_date=release_date))

        next_link_el = soup.select_one(".phantrang .wp-pagenavi a.nextpostslink, .phantrang .wp-pagenavi a[rel='next']")
        has_next = bool(next_link_el and next_link_el.get('href'))
        if not games and page > 1: has_next = False
        logger.info(f"Games found: {len(games)}, Has next page: {has_next}")

        categories: List[Dict[str, str]] = []
        category_links = soup.select("#Label7 .menu-menu-ben-trai-container li a")
        for cat_link in category_links:
            cat_name = cat_link.get_text(strip=True)
            cat_href = self._normalize_url(cat_link.get('href'))
            if cat_name and cat_href:
                path_parts = urlparse(cat_href).path.strip('/').split('/')
                if len(path_parts) > 1 and path_parts[0] == 'category':
                    slug = path_parts[1]
                    categories.append({"name": cat_name, "slug": slug})
        if categories:
            unique_categories_dict = {item['slug'].lower(): item for item in categories}
            categories = sorted(list(unique_categories_dict.values()), key=lambda x: x['name'])
        logger.info(f"Processed {len(categories)} unique categories.")

        return games, has_next, categories

    def get_game_details(self, url: str) -> Tuple[Dict[str, Any], Optional[str], Optional[str], List[str], List[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
        logger.info(f"Getting game details for: {url}")
        soup: Optional[BeautifulSoup] = self._get_soup(url)
        if not soup: return {}, None, None, [], [], None, []

        content_area = soup.select_one("div.post-body.entry-content") or soup.body
        if not content_area: return {}, None, None, [], [], None, []

        meta: Dict[str, Any] = {"url": url, "site": self.site_id}
        # ... (Title, Info Table, Cover Image, Description, SysReq, Screenshots extraction - keep previous robust logic) ...
        title_el = content_area.select_one("h1.post-title.entry-title")
        meta["title"] = self._clean_title(title_el.get_text(strip=True)) if title_el else "Unknown Title"
        if meta["title"] == "Unknown Title":
             info_table_title = self._extract_text(content_area, "tr:has(td:contains('NAME')) td[bgcolor='#FFF68F']")
             if info_table_title: meta["title"] = self._clean_title(info_table_title)
        logger.debug(f"Extracted Title: {meta['title']}")
        info_table = content_area.select_one("table[border='7']")
        cover_img_url: Optional[str] = None
        if info_table:
            meta["genre"] = self._extract_text(info_table, "tr:has(td:contains('GENRE')) td[bgcolor='#FFF68F']") or None
            meta["release_date"] = self._extract_text(info_table, "tr:has(td:contains('RELEASE')) td[bgcolor='#FFF68F']") or None
            meta["developer"] = self._extract_text(info_table, "tr:has(td:contains('DEVELOPER')) td[bgcolor='#FFF68F']") or None
            meta["publisher"] = self._extract_text(info_table, "tr:has(td:contains('PUBLISHER')) td[bgcolor='#FFF68F']") or None
            meta["language"] = self._extract_text(info_table, "tr:has(td:contains('LANGUAGE')) td[bgcolor='#FFF68F']") or None
            cover_td = info_table.select_one("tr > td[rowspan], tr > td:first-child")
            if cover_td:
                 img_tag = cover_td.find("img")
                 if img_tag and img_tag.get('src'): cover_img_url = self._resolve_image_url(img_tag.get('src'), url)
        meta["image"] = cover_img_url
        logger.debug(f"Info Table Meta: Genre={meta['genre']}, Date={meta['release_date']}, Image={'Yes' if meta['image'] else 'No'}")
        description_parts: List[str] = []
        desc_header = content_area.find(['h2', 'h3'], string=re.compile(r'Info|Description', re.I))
        start_node = desc_header if desc_header else info_table
        current_node = start_node.next_sibling if start_node else None
        stop_found = False
        while current_node and not stop_found:
             if isinstance(current_node, Tag):
                 if current_node.name in ['h2','h3'] and not re.search(r'Info|Description', current_node.get_text(strip=True), re.I): stop_found = True; break
                 if current_node.name == 'div' and ('su-spoiler' in current_node.get('class', []) or 'separator' in current_node.get('class', [])): stop_found = True; break
                 if current_node.name == 'p':
                     text = current_node.get_text(strip=True)
                     if text: description_parts.append(text)
             current_node = current_node.next_sibling
        description: Optional[str] = "\n\n".join(description_parts).strip() if description_parts else None
        logger.debug(f"Extracted Description: {'Yes' if description else 'No'}, Length: {len(description or '')}")
        sysreq_parts: List[str] = []
        sysreq_header = content_area.find(['h2','h3'], string=re.compile(r'System Requirements', re.I))
        if sysreq_header:
             current_node = sysreq_header.next_sibling
             stop_found = False
             while current_node and not stop_found:
                 if isinstance(current_node, Tag):
                     if current_node.name in ['h2','h3'] and 'system requirements' not in current_node.get_text(strip=True).lower(): stop_found = True; break
                     if current_node.name == 'div' and ('su-spoiler' in current_node.get('class', []) or 'separator' in current_node.get('class', [])): stop_found = True; break
                     if current_node.name in ['p', 'ul']: text = current_node.get_text('\n', strip=True); sysreq_parts.append(text)
                 elif not isinstance(current_node, Tag) and current_node.strip(): sysreq_parts.append(current_node.strip())
                 current_node = current_node.next_sibling
        sysreq: Optional[str] = "\n".join(sysreq_parts).strip() if sysreq_parts else None
        logger.debug(f"Extracted System Req: {'Yes' if sysreq else 'No'}, Length: {len(sysreq or '')}")
        screenshots: List[str] = []
        screenshot_tags = content_area.select("div.separator > a > img")
        logger.debug(f"Found {len(screenshot_tags)} potential screenshot images in separators.")
        for img_el in screenshot_tags:
            parent_separator = img_el.find_parent('div', class_='separator')
            preceding_spoiler = parent_separator.find_previous_sibling('div', class_='su-spoiler') if parent_separator else None
            if parent_separator and preceding_spoiler:
                src = img_el.get('src') or img_el.get('data-lazy-src')
                if src:
                    full_src = self._resolve_image_url(src, url)
                    if full_src and full_src != meta.get("image") and 'ytimg' not in full_src and not re.search(r'/s\d{2,3}(-c)?/', full_src):
                        if full_src not in screenshots: screenshots.append(full_src)
            else: logger.debug("Skipping image in separator, might not be screenshot.")
        logger.info(f"Found {len(screenshots)} screenshots.")

        # ===== Downloads & Password (REVISED LOGIC v2) =====
        downloads: List[Dict[str, Any]] = []
        passwords_found: Dict[str, str] = {}
        main_password: Optional[str] = None
    
        spoiler_elements = content_area.select("div.su-spoiler")
        logger.debug(f"Found {len(spoiler_elements)} spoiler elements for downloads.")

        for spoiler_el in spoiler_elements:
            spoiler_title_el = spoiler_el.select_one(".su-spoiler-title")
            group_title = self._clean_title(spoiler_title_el.get_text(strip=True)) if spoiler_title_el else "Download Links"
            group_password = None # Password specific to this group/table

            spoiler_content_el = spoiler_el.select_one(".su-spoiler-content")
            if not spoiler_content_el: continue

            table = spoiler_content_el.find("table")
            if table:
                headers = [th.get_text(strip=True).replace('Link', '').strip() for th in table.select("tr:first-child th")] # Clean headers
                data_rows = table.select("tr:not(:first-child)")

                for row_idx, row in enumerate(data_rows):
                    cells = row.find_all("td")
                    if not cells: continue

                    part_name_tag = cells[0].find('center')
                    part_name = part_name_tag.get_text(strip=True) if part_name_tag else cells[0].get_text(strip=True)

                    if "password" in part_name.lower() and len(cells) > 1:
                        pwd_tag = cells[1].find('center')
                        pwd_text = pwd_tag.get_text(strip=True) if pwd_tag else cells[1].get_text(strip=True)
                        if pwd_text:
                            # If it says "Password to extract", store as main password
                            if "extract" in part_name.lower():
                                if not main_password: main_password = pwd_text # Prioritize first "extract" password
                            elif not group_password: # Store as group password if not main
                                group_password = pwd_text
                            logger.debug(f"Password found in table row: {pwd_text} (Group: {group_title}, Main Candidate: {main_password is not None})")
                    elif len(cells) > 1:
                        # Check for Filecrypt-style password within cells like (Pass: XXX)
                        cell_pass_match = re.search(r'\((?:Password|Pass)\s*:\s*([\w.-]+)\)', row.get_text())
                        if cell_pass_match and not group_password and not main_password:
                            group_password = cell_pass_match.group(1)
                            logger.debug(f"Cell Password found: {group_password} for Group: {group_title}")

                        # Process download links in the row
                        if len(headers) == len(cells): # Standard table
                             for i, cell in enumerate(cells[1:], start=1):
                                 link_el = cell.find("a")
                                 if link_el and link_el.get('href'):
                                     href = self._normalize_url(link_el['href'])
                                     host_name = headers[i] if i < len(headers) else f"Link {i}"
                                     text = f"{host_name} - {part_name}"
                                     if href and not any(d['url'] == href for d in downloads):
                                         downloads.append({"url": href, "text": text, "group": group_title, "section": "Table Links"})
                        elif len(headers) < len(cells) and row_idx > 0: # Handle GTA V second row of hosts
                             link_cells = cells # All cells might contain links/hosts
                             host_names_row2 = [c.get_text(strip=True) for c in data_rows[row_idx-1].find_all('td')[1:]] # Get host names from previous row
                             part_name = data_rows[row_idx-1].find('td').get_text(strip=True) # Part name from previous row
                             for i, cell in enumerate(link_cells):
                                 link_el = cell.find("a")
                                 host_name = host_names_row2[i] if i < len(host_names_row2) else f"Alt Link {i+1}"
                                 if link_el and link_el.get('href'):
                                     href = self._normalize_url(link_el['href'])
                                     text = f"{host_name} - {part_name}"
                                     if href and not any(d['url'] == href for d in downloads):
                                         downloads.append({"url": href, "text": text, "group": group_title, "section": "Table Links (Alt Row)"})


            # Check for paragraph links (Mirrors)
            paragraph_links = spoiler_content_el.select("p a[href]")
            if paragraph_links:
                current_para_section = "Mirrors/Other"
                # Check if paragraph starts with "Update v..." to categorize
                first_p = spoiler_content_el.find('p')
                if first_p and first_p.get_text(strip=True).lower().startswith('update v'):
                     current_para_section = first_p.get_text(strip=True).split(':')[0] # e.g., "Update v1.0.813.11"

                for link_el in paragraph_links:
                     parent_p = link_el.find_parent('p')
                     if parent_p and "install:" in parent_p.get_text(strip=True).lower(): continue

                     href_raw = link_el.get('href')
                     text = link_el.get_text(strip=True) or "Download"
                     prev_text_node = link_el.previous_sibling
                     if isinstance(prev_text_node, str) and prev_text_node.strip():
                         prefix = prev_text_node.strip().rstrip('–- :')
                         if prefix and len(prefix) < 20: text = f"{prefix} - {text}"

                     if href_raw and not href_raw.strip().startswith(('javascript:', '#')):
                         href = self._normalize_url(href_raw)
                         if href and not any(d['url'] == href for d in downloads):
                             downloads.append({"url": href, "text": text, "group": group_title, "section": current_para_section})


            # Store group-specific password if found
            if group_password:
                passwords_found[group_title] = group_password

        # Final password determination
        password = main_password # Prioritize "Password to extract"
        if not password and passwords_found:
            # If no main password, maybe use the first group password found? Or leave null?
            # Let's leave it null unless explicitly "Password to extract"
            # You could add logic here to concatenate or choose if needed.
            logger.info(f"Group-specific passwords found but no main extraction password: {passwords_found}")
            # Optionally add group passwords to download link dicts?
            for link in downloads:
                 if link.get('group') in passwords_found:
                     link['password_hint'] = passwords_found[link['group']]

        logger.info(f"Found {len(downloads)} download links. Final Password: {password}")

        # --- Related Games ---
        # ... (unchanged) ...
        related_games: List[Dict[str, Any]] = []
        related_container = soup.select_one("div#related-posts")
        if related_container:
            logger.debug("Related posts container found.")
            for link_el in related_container.select("a[href]"):
                 related_url_raw = link_el.get('href')
                 if not related_url_raw or related_url_raw == url: continue
                 related_url = self._normalize_url(related_url_raw)
                 if not related_url: continue
                 img_tag = link_el.find("img.maskolis_img")
                 related_title_text = ""
                 related_image = None
                 title_div = link_el.find("div")
                 if title_div: related_title_text = title_div.get_text(strip=True)
                 if img_tag:
                     related_image = self._resolve_image_url(img_tag.get('src'), related_url)
                     if not related_title_text: related_title_text = img_tag.get('alt', '')
                 related_title = self._clean_title(related_title_text or related_url.split('/')[-1].replace('-', ' ').title())
                 if related_title and related_title.lower() != meta["title"].lower():
                     if not any(g['url'] == related_url for g in related_games):
                         related_games.append(self._format_game_data(title=related_title, url=related_url, image=related_image))
                 if len(related_games) >= 8: break
        logger.info(f"Found {len(related_games)} related games.")

        return meta, description, sysreq, screenshots, downloads, password, related_games

    def search_games(self, query: str) -> List[Dict[str, Any]]:
        # ... (unchanged from previous fix) ...
        if not self.base_url: return []
        search_url = f"{self.base_url}/?s={quote(query)}"
        logger.info(f"Searching GamePCISO with URL: {search_url}")
        soup: Optional[BeautifulSoup] = self._get_soup(search_url)
        if not soup: return []

        games: List[Dict[str, Any]] = []
        for game_el in soup.select("div.post.bar.hentry"):
            link_el = game_el.select_one("h2.post-title.entry-title a")
            if not link_el or not link_el.get('href'): continue
            game_url = self._normalize_url(link_el['href'])
            if not game_url: continue
            cleaned_title = self._clean_title(link_el.get_text(strip=True))
            img_el = game_el.select_one(".post-body div[id^='summary'] img, .post-body img")
            image_url: Optional[str] = None
            if img_el:
                src_candidate = img_el.get('src') or img_el.get('data-lazy-src')
                if src_candidate: image_url = self._resolve_image_url(src_candidate, game_url)
            release_date = None
            date_el = game_el.select_one(".postmeta .date, .entry-date, time.published")
            if date_el: release_date = date_el.get_text(strip=True) or date_el.get('datetime')
            games.append(self._format_game_data(title=cleaned_title, url=game_url, image=image_url, release_date=release_date))
            if len(games) >= 20: break
        logger.info(f"Found {len(games)} results for search query: '{query}'")
        return games