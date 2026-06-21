import asyncio
import json
import re
from playwright.async_api import async_playwright

MENU_URL = "https://www.hellofresh.fr/panier-repas/menu-de-la-semaine"

MENU_LABELS = {
    "familial": ["familial", "famille", "family"],
    "rapide": ["rapide", "quick", "express"],
    "veggie": ["végétarien", "veggie", "végé"],
}


async def _accept_cookies(page):
    for selector in [
        "#onetrust-accept-btn-handler",
        'button[id*="accept"]',
        'button:text("Accepter")',
        'button:text("Tout accepter")',
    ]:
        try:
            await page.click(selector, timeout=3000)
            await asyncio.sleep(1)
            return
        except Exception:
            pass


async def _extract_cards(page) -> list[dict]:
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(3)

    cards = await page.evaluate("""
        () => {
            const results = [];
            const seen = new Set();

            const candidates = [
                ...document.querySelectorAll('a[href*="/recipes/"]'),
                ...document.querySelectorAll('a[href*="/recettes/"]'),
            ];

            for (const link of candidates) {
                const url = link.href;
                if (seen.has(url)) continue;
                seen.add(url);

                const card = link.closest('li, article, [class*="card"], [class*="Card"]') || link;
                const img = card.querySelector('img');
                const nameEl = card.querySelector('h3, h4, h2, [class*="name"], [class*="title"], [class*="Name"]');
                const descEl = card.querySelector('p, [class*="description"], [class*="tagline"]');
                const timeEl = card.querySelector('[class*="time"], [class*="Time"], time');

                const name = nameEl ? nameEl.innerText.trim() : '';
                if (!name || name.length < 3) continue;

                results.push({
                    name,
                    url,
                    slug: url.split('/').filter(Boolean).pop(),
                    description: descEl ? descEl.innerText.trim().slice(0, 200) : '',
                    image: img ? (img.src || img.dataset.src || '') : '',
                    time: timeEl ? timeEl.innerText.trim() : '',
                });
            }
            return results;
        }
    """)
    return cards


async def _click_menu_tab(page, menu_type: str) -> bool:
    labels = MENU_LABELS.get(menu_type, [menu_type])
    for label in labels:
        for selector in [
            f'a:text-matches("{label}", "i")',
            f'button:text-matches("{label}", "i")',
            f'[role="tab"]:text-matches("{label}", "i")',
            f'li:text-matches("{label}", "i")',
        ]:
            try:
                await page.click(selector, timeout=3000)
                await asyncio.sleep(2)
                return True
            except Exception:
                pass
    return False


async def get_all_menus(menu_types: list[str] | None = None) -> dict[str, list[dict]]:
    if menu_types is None:
        menu_types = list(MENU_LABELS.keys())

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="fr-FR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        print(f"Loading {MENU_URL} ...")
        await page.goto(MENU_URL, wait_until="domcontentloaded", timeout=60000)
        await _accept_cookies(page)
        await asyncio.sleep(4)

        menus: dict[str, list[dict]] = {}

        for menu_type in menu_types:
            print(f"Scraping menu: {menu_type}")
            clicked = await _click_menu_tab(page, menu_type)
            if not clicked:
                # Try anchor-based navigation
                anchor = f"menu-{menu_type}"
                await page.goto(f"{MENU_URL}#{anchor}", wait_until="domcontentloaded")
                await asyncio.sleep(3)

            cards = await _extract_cards(page)
            if cards:
                menus[menu_type] = cards
                print(f"  → {len(cards)} recipes found")
            else:
                print(f"  → No recipes found for '{menu_type}'")

        await browser.close()
        return menus


def get_all_menus_sync(menu_types: list[str] | None = None) -> dict[str, list[dict]]:
    return asyncio.run(get_all_menus(menu_types))
