import json
import re
import time
import asyncio
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.hellofresh.fr"
MENU_URL = f"{BASE}/panier-repas/menu-de-la-semaine"

MENU_ANCHORS = {
    "familial": "menu-familial",
    "rapide":   "menu-rapide",
    "veggie":   "menu-veggie",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.fr/",
}


def _fetch(url: str, retries: int = 3) -> requests.Response:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"  fetch attempt {attempt+1} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(3)
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def _extract_next_data(html: str) -> dict:
    """Extract the __NEXT_DATA__ JSON blob embedded in Next.js pages."""
    tag = BeautifulSoup(html, "html.parser").find("script", {"id": "__NEXT_DATA__"})
    if tag and tag.string:
        return json.loads(tag.string)
    return {}


def _find_recipes_in_json(obj, results=None, depth=0):
    """Recursively walk the Next.js data tree to find recipe objects."""
    if results is None:
        results = []
    if depth > 15:
        return results

    if isinstance(obj, dict):
        # A recipe object typically has slug + name + a link
        slug = obj.get("slug") or obj.get("id") or ""
        name = obj.get("name") or obj.get("headline") or obj.get("title") or ""
        if name and slug and len(name) > 3:
            url = obj.get("websiteUrl") or obj.get("url") or f"{BASE}/recipes/{slug}"
            image = ""
            imgs = obj.get("imagePath") or obj.get("image") or ""
            if isinstance(imgs, str) and imgs:
                image = imgs if imgs.startswith("http") else f"https://img.hellofresh.com/f_auto,fl_lossy,q_auto,w_500/hellofresh_s3/{imgs}"
            elif isinstance(imgs, dict):
                image = imgs.get("url", "")
            results.append({
                "name": name,
                "slug": slug,
                "url": url,
                "image": image,
                "description": obj.get("description", ""),
            })
        for v in obj.values():
            _find_recipes_in_json(v, results, depth + 1)

    elif isinstance(obj, list):
        for item in obj:
            _find_recipes_in_json(item, results, depth + 1)

    return results


def _cards_from_html(html: str) -> list[dict]:
    """Fallback: parse recipe links directly from the page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    seen, cards = set(), []

    for a in soup.find_all("a", href=re.compile(r"/recipes/")):
        href = a.get("href", "")
        url = urljoin(BASE, href)
        if url in seen:
            continue
        seen.add(url)

        slug = href.rstrip("/").split("/")[-1]
        img = a.find("img")
        name_el = a.find(["h3", "h4", "h2"])
        name = name_el.get_text(strip=True) if name_el else ""
        if not name and img:
            name = img.get("alt", "")
        if not name or len(name) < 3:
            continue

        cards.append({
            "name": name,
            "slug": slug,
            "url": url,
            "image": img["src"] if img and img.get("src") else "",
            "description": "",
        })

    return cards


def get_all_menus(menu_types: list[str] | None = None) -> dict[str, list[dict]]:
    if menu_types is None:
        menu_types = list(MENU_ANCHORS.keys())

    print(f"Fetching {MENU_URL} ...")
    r = _fetch(MENU_URL)
    html = r.text

    print(f"  Page fetched ({len(html)} bytes). Extracting data...")

    # Strategy 1: __NEXT_DATA__ JSON
    next_data = _extract_next_data(html)
    all_recipes = []
    if next_data:
        print("  Found __NEXT_DATA__, searching for recipes...")
        all_recipes = _find_recipes_in_json(next_data)
        # Deduplicate
        seen = set()
        unique = []
        for r in all_recipes:
            if r["slug"] not in seen:
                seen.add(r["slug"])
                unique.append(r)
        all_recipes = unique
        print(f"  Found {len(all_recipes)} recipes in __NEXT_DATA__")

    # Strategy 2: parse HTML links
    if not all_recipes:
        print("  No __NEXT_DATA__ recipes, falling back to HTML parsing...")
        all_recipes = _cards_from_html(html)
        print(f"  Found {len(all_recipes)} recipe links in HTML")

    if not all_recipes:
        print("  WARNING: No recipes found at all.")
        return {}

    # If we can't distinguish menus, put everything under the default
    menus = {}
    for menu_type in menu_types:
        menus[menu_type] = all_recipes  # same list for now; HF doesn't always separate by anchor
    return menus


def get_all_menus_sync(menu_types: list[str] | None = None) -> dict[str, list[dict]]:
    return get_all_menus(menu_types)
