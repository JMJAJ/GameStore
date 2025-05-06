from flask import Flask, request, jsonify, render_template, url_for, redirect
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)
BASE_URL = "https://www.ovagames.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def get_soup(url):
    res = requests.get(url, headers=HEADERS, timeout=10)
    res.raise_for_status()
    return BeautifulSoup(res.text, "html.parser")


def scrape_games_list(page=1):
    url = f"{BASE_URL}/page/{page}/" if page > 1 else BASE_URL
    soup = get_soup(url)
    games = []
    # Use .post-inside to select each game card
    for post in soup.select(".post-inside"):  
        a = post.select_one(".post-inside a[href]")
        if not a:
            continue
        title = a.get_text(strip=True)
        link = a['href']
        img = post.select_one(".post-wrapper img[src]")
        img_url = img['src'] if img else url_for('static', filename='css/fallback.png')
        games.append({
            "title": title,
            "url": link,
            "image": img_url
        })
    has_next = bool(soup.select_one(".wp-pagenavi a.nextpostslink"))
    return games, has_next


def scrape_game_details(page_url):
    soup = get_soup(page_url)
    # Extract top metadata from strong tags in the first content block
    meta = {}
    for strong in soup.select(".post-content p strong"):
        text = strong.get_text(strip=True)
        if ':' in text:
            key, val = text.split(':', 1)
            meta[key.strip().lower().replace(' ', '_')] = val.strip()
    # Title fallback
    if 'title' not in meta:
        h1 = soup.select_one(".post-content h1")
        meta['title'] = h1.get_text(strip=True) if h1 else None
    # Tabs
    description = ''
    desc_div = soup.select_one("#description .wp-tab-content-wrapper")
    if desc_div:
        description = desc_div.get_text(separator="\n", strip=True)
    sysreq = ''
    sys_div = soup.select_one("#system_requirements .wp-tab-content-wrapper")
    if sys_div:
        sysreq = sys_div.get_text(separator="\n", strip=True)
    # Screenshots
    screenshots = [img['src'] for img in soup.select("#description + ul img, .wp-tab-content-wrapper img[src]")]
    # Download links & password
    downloads = [a['href'] for a in soup.select(".dl-wraps-item a[href]")]
    pwd = ''
    pwd_tag = soup.select_one(".su-box-content")
    if pwd_tag:
        pwd = pwd_tag.get_text(strip=True)
    return meta, description, sysreq, screenshots, downloads, pwd


@app.route('/')
def home():
    return redirect(url_for('view_games', page=1))


@app.route('/games/<int:page>')
def view_games(page):
    games, has_next = scrape_games_list(page)
    return render_template('index.html', games=games, page=page, has_next=has_next)


@app.route('/game')
def view_game():
    game_url = request.args.get('url')
    if not game_url:
        return redirect(url_for('home'))
    meta, description, sysreq, screenshots, downloads, password = scrape_game_details(game_url)
    return render_template('game.html', meta=meta, description=description,
                           sysreq=sysreq, screenshots=screenshots,
                           downloads=downloads, password=password)


@app.route('/api/games')
def api_games():
    page = int(request.args.get('page', 1))
    games, has_next = scrape_games_list(page)
    return jsonify({"games": games, "has_next": has_next})


@app.route('/api/game')
def api_game():
    url = request.args.get('url')
    meta, description, sysreq, screenshots, downloads, password = scrape_game_details(url)
    return jsonify({**meta, "description": description,
                    "system_requirements": sysreq,
                    "screenshots": screenshots,
                    "download_links": downloads,
                    "download_password": password})


if __name__ == '__main__':
    app.run(debug=True)