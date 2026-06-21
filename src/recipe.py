import json
import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.hellofresh.fr"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_QTY_RE = re.compile(
    r"(?P<amount>[\d,./]+)\s*"
    r"(?P<unit>g|gr|kg|ml|cl|L|l|pièce[s]?|unité[s]?|c\.à\.s|c\.à\.c|tbsp|tsp|bouquet[s]?|tranche[s]?|gousse[s]?)?\s*"
    r"(?:de\s+)?(?P<name>.+)",
    re.IGNORECASE,
)


def _parse_quantity(raw: str) -> dict:
    raw = raw.strip()
    m = _QTY_RE.match(raw)
    if m:
        amount_str = m.group("amount").replace(",", ".")
        try:
            amount = float(eval(amount_str))
        except Exception:
            amount = None
        return {
            "raw": raw,
            "amount": amount,
            "unit": (m.group("unit") or "").lower().rstrip("s"),
            "name": m.group("name").strip(),
        }
    return {"raw": raw, "amount": None, "unit": "", "name": raw}


def _fetch_html(url: str) -> str:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"    fetch attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(3)
    return ""


def _extract_next_data(html: str) -> dict:
    tag = BeautifulSoup(html, "html.parser").find("script", {"id": "__NEXT_DATA__"})
    if tag and tag.string:
        return json.loads(tag.string)
    return {}


def _find_value(obj, *keys):
    """Find first matching key in a nested dict/list."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k]:
                return obj[k]
        for v in obj.values():
            found = _find_value(v, *keys)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_value(item, *keys)
            if found:
                return found
    return None


def _parse_recipe_from_next_data(data: dict, url: str) -> dict | None:
    """Extract recipe from __NEXT_DATA__ props."""
    if not data:
        return None

    # HellFresh stores recipe under props.pageProps.recipe or similar
    recipe_obj = None
    for candidate_key in ("recipe", "recipeItem", "recipeDetails"):
        r = _find_value(data.get("props", {}), candidate_key)
        if r and isinstance(r, dict) and r.get("name"):
            recipe_obj = r
            break

    if not recipe_obj:
        # Try flat search
        props = data.get("props", {}).get("pageProps", {})
        for v in props.values():
            if isinstance(v, dict) and v.get("name") and v.get("ingredients"):
                recipe_obj = v
                break

    if not recipe_obj:
        return None

    # Parse ingredients
    raw_ingredients = recipe_obj.get("ingredients", []) or recipe_obj.get("yieldedIngredients", [])
    ingredients = []
    for ing in raw_ingredients:
        if isinstance(ing, dict):
            name = ing.get("name", "") or ing.get("ingredient", {}).get("name", "") if isinstance(ing.get("ingredient"), dict) else ""
            amount = ing.get("amount") or ing.get("quantity")
            unit = ing.get("unit", {})
            if isinstance(unit, dict):
                unit = unit.get("name", "") or unit.get("abbreviation", "")
            raw_str = f"{amount or ''} {unit or ''} {name}".strip()
            parsed = _parse_quantity(raw_str)
            if parsed["name"]:
                ingredients.append(parsed)

    # Parse steps
    steps_raw = recipe_obj.get("steps", []) or recipe_obj.get("instructions", [])
    steps = []
    for s in steps_raw:
        if isinstance(s, dict):
            text = s.get("instructionsMarkdown") or s.get("instructions") or s.get("description") or ""
            # Strip markdown
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text).strip()
            if text:
                steps.append(text)
        elif isinstance(s, str) and s.strip():
            steps.append(s.strip())

    # Image
    image = ""
    img_path = recipe_obj.get("imagePath") or recipe_obj.get("image") or ""
    if isinstance(img_path, str) and img_path:
        image = img_path if img_path.startswith("http") else f"https://img.hellofresh.com/f_auto,fl_lossy,q_auto,w_800/hellofresh_s3/{img_path}"

    # Times
    prep = recipe_obj.get("prepTime") or ""
    cook = recipe_obj.get("totalTime") or recipe_obj.get("cookingTime") or ""
    times = []
    for t in (prep, cook):
        if t:
            mins = re.sub(r"PT(\d+)M", r"\1 min", str(t))
            times.append(mins)

    servings = recipe_obj.get("servingsMapping", {})
    if isinstance(servings, list) and servings:
        base = int(servings[0].get("servings", 2))
    else:
        base = int(recipe_obj.get("servings", 2) or 2)

    return {
        "name": recipe_obj.get("name", ""),
        "url": url,
        "image": image,
        "times": [t for t in times if t],
        "steps": steps,
        "ingredients": ingredients,
        "base_servings": base,
    }


def _parse_recipe_from_html(html: str, url: str) -> dict:
    """Fallback HTML parser when Next.js data isn't available."""
    soup = BeautifulSoup(html, "html.parser")

    name = soup.find("h1")
    name = name.get_text(strip=True) if name else ""

    img = soup.find("img", {"src": re.compile(r"hellofresh|recipe", re.I)})
    image = img["src"] if img and img.get("src") else ""

    # Ingredients: look for common list patterns
    ingredients = []
    for li in soup.select("ul li"):
        text = li.get_text(separator=" ", strip=True)
        if 2 < len(text) < 100:
            ingredients.append(_parse_quantity(text))

    # Steps: ordered list
    steps = [li.get_text(separator=" ", strip=True) for li in soup.select("ol li") if len(li.get_text()) > 15]

    return {
        "name": name,
        "url": url,
        "image": image,
        "times": [],
        "steps": steps,
        "ingredients": ingredients,
        "base_servings": 2,
    }


def scrape_recipe(url: str) -> dict:
    print(f"  Fetching recipe: {url}")
    html = _fetch_html(url)
    if not html:
        return {"name": "", "url": url, "image": "", "times": [], "steps": [], "ingredients": [], "base_servings": 2}

    next_data = _extract_next_data(html)
    recipe = _parse_recipe_from_next_data(next_data, url)

    if recipe and recipe.get("name"):
        print(f"    → '{recipe['name']}' ({len(recipe['ingredients'])} ingredients, {len(recipe['steps'])} steps)")
        return recipe

    # Fallback
    print("    → __NEXT_DATA__ parse failed, using HTML fallback")
    return _parse_recipe_from_html(html, url)


def scrape_recipes_sync(urls: list[str]) -> list[dict]:
    results = []
    for url in urls:
        try:
            r = scrape_recipe(url)
            results.append(r)
            time.sleep(1)  # polite delay
        except Exception as e:
            print(f"  Error scraping {url}: {e}")
    return results
