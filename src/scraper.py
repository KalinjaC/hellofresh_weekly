import re
import time
import unicodedata

import requests
from bs4 import BeautifulSoup
try:
    from duckduckgo_search import DDGS
    _DDG_AVAILABLE = True
except ImportError:
    _DDG_AVAILABLE = False

BASE = "https://www.hellofresh.fr"
MENUS_URL = f"{BASE}/menus"
RECIPES_URL = f"{BASE}/recipes"

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


def _fetch(url: str, params: dict | None = None) -> str:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=_HEADERS, params=params, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"  fetch attempt {attempt+1} failed for {url}: {e}")
            if attempt < 2:
                time.sleep(3)
    raise RuntimeError(f"Failed to fetch {url}")


def _slugify(text: str) -> str:
    """Normalize to ASCII, lowercase, spaces to hyphens."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", " ", text).strip()


def _extract_menu_cards(html: str) -> list[dict]:
    """Extract recipe cards from /menus page."""
    soup = BeautifulSoup(html, "lxml")
    seen, cards = set(), []

    # Recipe names are typically in h3/h4, images have RFR IDs
    # Try multiple selector strategies
    name_els = (
        soup.select("h3, h4")
        or soup.find_all(["h3", "h4"])
    )

    for el in name_els:
        name = el.get_text(strip=True)
        if len(name) < 5 or len(name) > 120:
            continue
        if name in seen:
            continue
        # Skip navigation/UI headings
        if any(w in name.lower() for w in ["menu", "découvr", "commandez", "panier", "recette", "semaine", "plan"]):
            continue

        seen.add(name)

        # Try to find parent card for image and tags
        card = el.find_parent(["li", "article", "div", "section"])
        img = card.find("img") if card else None
        image_url = ""
        if img:
            image_url = img.get("src") or img.get("data-src") or ""

        # Extract tags from badges
        tags = []
        if card:
            for badge in card.find_all(string=re.compile(r"Rapide|Végétar|Épicé|Nouveau|Protéines|Super", re.I)):
                tag = badge.strip()
                if tag and len(tag) < 30:
                    tags.append(tag)

        # Extract time from text
        time_match = re.search(r"(\d+)\s*min", card.get_text() if card else "", re.I)
        duration = f"{time_match.group(1)} min" if time_match else ""

        cards.append({
            "name": name,
            "image": image_url,
            "tags": tags,
            "duration": duration,
            "url": "",  # filled by search step
            "slug": "",
        })

    print(f"  Extracted {len(cards)} recipe names from /menus")
    return cards


def _search_on_hellofresh(name: str) -> str:
    """Search HellFresh's own /recipes catalog. Works for indexed recipes."""
    words = [w for w in _slugify(name).split() if len(w) > 2][:4]
    query = " ".join(words)
    if not query:
        return ""
    try:
        html = _fetch(RECIPES_URL, params={"q": query})
    except Exception:
        return ""
    soup = BeautifulSoup(html, "lxml")
    recipe_links = soup.find_all("a", href=re.compile(r"^/recipes/[a-z]"))
    name_words = set(_slugify(name).split())
    best_url, best_score = "", 0
    for link in recipe_links:
        href = link.get("href", "")
        slug_words = set(href.split("/")[-1].split("-")[:-1])
        score = len(name_words & slug_words)
        if score > best_score:
            best_score = score
            best_url = f"{BASE}{href}"
    return best_url if best_score >= 2 else ""


def _search_via_duckduckgo(name: str) -> str:
    """Fallback: search DuckDuckGo for the recipe on hellofresh.fr (finds new/unlisted recipes)."""
    if not _DDG_AVAILABLE:
        return ""
    query = f'site:hellofresh.fr/recipes "{name}"'
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        for r in results:
            href = r.get("href", "")
            if "hellofresh.fr/recipes/" in href and href.count("/") >= 4:
                return href
    except Exception as e:
        print(f"    DuckDuckGo search failed: {e}")
    return ""


def _search_recipe_url(name: str) -> str:
    """Find the HellFresh recipe page URL for a given recipe name."""
    # Try HellFresh catalog first (fast)
    url = _search_on_hellofresh(name)
    if url:
        return url
    # Fallback: DuckDuckGo (finds new/unlisted recipes)
    time.sleep(0.5)
    url = _search_via_duckduckgo(name)
    if url:
        print(f"    → Found via DuckDuckGo: {url}")
    return url


def get_all_menus(max_recipes: int = 60) -> dict[str, list[dict]]:
    """Returns {"semaine": [recipe_cards]}."""
    print(f"Fetching {MENUS_URL} ...")
    html = _fetch(MENUS_URL)
    print(f"  Got {len(html)} bytes")

    cards = _extract_menu_cards(html)
    if not cards:
        return {}

    # Limit
    cards = cards[:max_recipes]

    # For each card, try to find its recipe page URL
    print(f"  Searching recipe pages for {len(cards)} recipes...")
    for i, card in enumerate(cards):
        url = _search_recipe_url(card["name"])
        card["url"] = url
        if url:
            card["slug"] = url.rstrip("/").split("/")[-1]
        if (i + 1) % 10 == 0:
            print(f"    {i+1}/{len(cards)} done")
        time.sleep(0.5)  # polite delay

    found = sum(1 for c in cards if c["url"])
    print(f"  Found recipe pages for {found}/{len(cards)} recipes")

    return {"semaine": cards}


def get_all_menus_sync(menu_types: list[str] | None = None, max_recipes: int = 60) -> dict[str, list[dict]]:
    return get_all_menus(max_recipes=max_recipes)
