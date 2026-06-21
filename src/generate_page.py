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


def main():
    cfg = load_config()
    default_menu = cfg["default_menu"]
    adults = cfg["adults"]

    print(f"Config: default_menu={default_menu}, adults={adults}")

    # --- Scrape menus ---
    from scraper import get_all_menus_sync
    menus_raw = get_all_menus_sync()

    if not menus_raw:
        print("ERROR: No menus scraped. Aborting.")
        sys.exit(1)

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
        recipes = scrape_recipes_sync(urls)

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
