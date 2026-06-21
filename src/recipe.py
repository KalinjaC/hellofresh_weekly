import asyncio
import re
from playwright.async_api import async_playwright

# Regex to parse French quantity strings like "200 g", "1 cuillère à soupe", "2 pièces"
_QTY_RE = re.compile(
    r"(?P<amount>[\d,./]+)\s*(?P<unit>g|gr|kg|ml|cl|L|l|pièce[s]?|unité[s]?|c\.à\.s|c\.à\.c|tbsp|tsp|bouquet[s]?|tranche[s]?|gousse[s]?)?\s*(?:de\s+)?(?P<name>.+)",
    re.IGNORECASE,
)


def _parse_quantity(raw: str) -> dict:
    raw = raw.strip()
    m = _QTY_RE.match(raw)
    if m:
        amount_str = m.group("amount").replace(",", ".").replace("/", "/")
        try:
            amount = float(eval(amount_str))  # handles "1/2" etc.
        except Exception:
            amount = None
        return {
            "raw": raw,
            "amount": amount,
            "unit": (m.group("unit") or "").lower().rstrip("s"),
            "name": m.group("name").strip(),
        }
    return {"raw": raw, "amount": None, "unit": "", "name": raw}


async def scrape_recipe(url: str) -> dict:
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
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        data = await page.evaluate("""
            () => {
                const getText = (el) => el ? el.innerText.trim() : '';
                const getAttr = (el, attr) => el ? (el.getAttribute(attr) || '') : '';

                // Name
                const name = getText(document.querySelector('h1'));

                // Image
                const img = document.querySelector('img[src*="recipe"], img[class*="hero"], [class*="Hero"] img, main img');
                const image = img ? img.src : '';

                // Time (prep + cook)
                const times = [...document.querySelectorAll('[class*="time"], [class*="Time"], [class*="duration"], [class*="Duration"]')]
                    .map(el => el.innerText.trim()).filter(Boolean);

                // Ingredients — two common patterns on HF
                const ingredientEls = [
                    ...document.querySelectorAll('[class*="ingredient"] [class*="name"], [class*="Ingredient"] [class*="Name"]'),
                    ...document.querySelectorAll('[data-test-id*="ingredient"]'),
                    ...document.querySelectorAll('[class*="IngredientItem"], [class*="ingredientItem"]'),
                ];

                const ingredients = ingredientEls.map(el => {
                    const amountEl = el.closest('li, [class*="item"]')?.querySelector('[class*="amount"], [class*="Amount"], [class*="quantity"]');
                    const nameEl = el.closest('li, [class*="item"]')?.querySelector('[class*="name"], [class*="Name"]') || el;
                    return {
                        amount: amountEl ? amountEl.innerText.trim() : '',
                        name: nameEl ? nameEl.innerText.trim() : el.innerText.trim(),
                    };
                }).filter(i => i.name);

                // Fallback: scrape raw ingredient list
                if (ingredients.length === 0) {
                    const listItems = [...document.querySelectorAll('ul li')].filter(li => {
                        const text = li.innerText.trim();
                        return text.length > 2 && text.length < 100;
                    });
                    listItems.slice(0, 20).forEach(li => {
                        ingredients.push({ amount: '', name: li.innerText.trim() });
                    });
                }

                // Steps
                const stepEls = [
                    ...document.querySelectorAll('[class*="step"] [class*="description"], [class*="Step"] [class*="Description"]'),
                    ...document.querySelectorAll('[data-test-id*="step"]'),
                    ...document.querySelectorAll('ol li'),
                ];
                const steps = stepEls.map(el => el.innerText.trim()).filter(s => s.length > 10);

                // Servings (base servings on the page, usually 2 or 4)
                const servingsEl = document.querySelector('[class*="serving"], [class*="Serving"], [data-test-id*="serving"]');
                const servings = servingsEl ? parseInt(servingsEl.innerText) || 2 : 2;

                return { name, image, times, ingredients, steps, servings, url: window.location.href };
            }
        """)

        await browser.close()

        # Parse ingredient quantities
        parsed_ingredients = []
        for ing in data.get("ingredients", []):
            raw = f"{ing['amount']} {ing['name']}".strip() if ing["amount"] else ing["name"]
            parsed = _parse_quantity(raw)
            parsed_ingredients.append(parsed)

        return {
            "name": data.get("name", ""),
            "url": data.get("url", url),
            "image": data.get("image", ""),
            "times": data.get("times", []),
            "steps": data.get("steps", []),
            "ingredients": parsed_ingredients,
            "base_servings": data.get("servings", 2),
        }


async def scrape_recipes_batch(urls: list[str]) -> list[dict]:
    results = []
    for url in urls:
        try:
            print(f"  Scraping recipe: {url}")
            recipe = await scrape_recipe(url)
            results.append(recipe)
        except Exception as e:
            print(f"  Error scraping {url}: {e}")
    return results


def scrape_recipes_sync(urls: list[str]) -> list[dict]:
    return asyncio.run(scrape_recipes_batch(urls))
