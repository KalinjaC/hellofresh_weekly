#!/usr/bin/env python3
"""
Main orchestrator: scrapes HellFresh, generates the static PWA page, writes to output/.
Run locally: python src/generate_page.py
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).parent.parent
SRC = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"
STATIC_DIR = ROOT / "static"
TEMPLATES_DIR = SRC / "templates"


def load_config() -> dict:
    cfg_path = ROOT / "config.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    return {
        "default_menu": cfg.get("default_menu", "familial"),
        "adults": int(cfg.get("adults", 4)),
    }


def _write_fallback_page(output_dir: Path, reason: str):
    """Generates a minimal error page so GitHub Pages always has something to serve."""
    output_dir.mkdir(exist_ok=True)
    now = datetime.now().strftime("%d/%m/%Y à %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Menu HellFresh — Erreur</title>
<script src="https://cdn.tailwindcss.com"></script>
</head><body class="bg-gray-50 flex items-center justify-center min-h-screen">
<div class="text-center p-8">
  <div class="text-6xl mb-4">🍽️</div>
  <h1 class="text-2xl font-bold text-gray-700 mb-2">Menu indisponible</h1>
  <p class="text-gray-500 mb-4">{reason}</p>
  <p class="text-xs text-gray-300">Dernière tentative : {now}</p>
  <p class="text-xs text-gray-300 mt-2">Le menu sera automatiquement remis à jour samedi prochain.</p>
</div>
</body></html>"""
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    print(f"Fallback page written to {output_dir / 'index.html'}")


def main():
    cfg = load_config()
    default_menu = cfg["default_menu"]
    adults = cfg["adults"]

    print(f"Config: default_menu={default_menu}, adults={adults}")

    # --- Scrape menus ---
    from scraper import get_all_menus_sync
    try:
        menus_raw = get_all_menus_sync()
    except Exception as e:
        print(f"ERROR during scraping: {e}")
        menus_raw = {}

    if not menus_raw:
        print("No menus scraped — generating fallback page.")
        _write_fallback_page(OUTPUT_DIR, "Impossible de récupérer le menu HellFresh cette semaine.")
        # Copy static files so PWA still works
        for f in STATIC_DIR.glob("*"):
            (OUTPUT_DIR / f.name).write_bytes(f.read_bytes())
        return  # Exit cleanly so GitHub Actions deploys the fallback

    # Ensure default menu is first (or present)
    if default_menu not in menus_raw:
        default_menu = next(iter(menus_raw))
        print(f"Warning: default menu not found, using '{default_menu}'")

    # --- Scrape recipes for each menu ---
    from recipe import scrape_recipes_sync
    from shopping_list import build_shopping_list

    menus_full: dict[str, dict] = {}

    for menu_type, cards in menus_raw.items():
        print(f"\nFetching recipes for menu '{menu_type}' ({len(cards)} dishes)...")
        urls = [c["url"] for c in cards if c.get("url")]
        try:
            recipes = scrape_recipes_sync(urls)
        except Exception as e:
            print(f"  Warning: recipe scraping failed for '{menu_type}': {e}")
            recipes = []

        shopping = build_shopping_list(recipes, adults)

        # Attach thumbnail from card scrape if recipe image missing
        for i, recipe in enumerate(recipes):
            if not recipe.get("image") and i < len(cards):
                recipe["image"] = cards[i].get("image", "")

        menus_full[menu_type] = {
            "cards": cards,
            "recipes": recipes,
            "shopping_list": shopping,
        }

    # --- Render template ---
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("index.html.j2")

    week_label = datetime.now().strftime("Semaine %W · %Y")
    generated_at = datetime.now().strftime("%d/%m/%Y à %H:%M")

    html = template.render(
        menus=menus_full,
        default_menu=default_menu,
        adults=adults,
        week_label=week_label,
        generated_at=generated_at,
        menus_json=json.dumps(menus_full, ensure_ascii=False),
        adults_json=adults,
    )

    # --- Write output ---
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_file = OUTPUT_DIR / "index.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"\nPage generated: {out_file}")

    # Copy static files
    for f in STATIC_DIR.glob("*"):
        dest = OUTPUT_DIR / f.name
        dest.write_bytes(f.read_bytes())
        print(f"Copied: {f.name}")

    print("\nDone.")


if __name__ == "__main__":
    main()
