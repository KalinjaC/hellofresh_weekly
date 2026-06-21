import re
from collections import defaultdict

# Unit normalization: maps variants to a canonical unit
_UNIT_MAP = {
    "gr": "g", "gramme": "g", "grammes": "g",
    "kilogramme": "kg", "kilogrammes": "kg",
    "millilitre": "ml", "millilitres": "ml",
    "centilitre": "cl", "centilitres": "cl",
    "litre": "l", "litres": "l",
    "c.à.s": "càs", "tbsp": "càs", "cuillère à soupe": "càs",
    "c.à.c": "càc", "tsp": "càc", "cuillère à café": "càc",
    "pièce": "", "pièces": "", "unité": "", "unités": "",
    "tranche": "tranche", "tranches": "tranche",
    "bouquet": "bouquet", "bouquets": "bouquet",
    "gousse": "gousse", "gousses": "gousse",
}

# Category keywords for sorting the shopping list
_CATEGORY_KEYWORDS = {
    "Légumes & Herbes": [
        "oignon", "carotte", "courgette", "tomate", "poivron", "aubergine",
        "brocoli", "épinard", "salade", "laitue", "persil", "ciboulette",
        "basilic", "coriandre", "thym", "romarin", "ail", "échalote",
        "céleri", "poireau", "navet", "radis", "concombre", "fenouil",
        "champignon", "haricot", "pois", "maïs", "artichaut", "betterave",
    ],
    "Viandes & Poissons": [
        "poulet", "boeuf", "veau", "porc", "agneau", "dinde", "canard",
        "saumon", "thon", "cabillaud", "crevette", "moule", "seiche",
        "truite", "sole", "merlu", "lapin", "filet",
    ],
    "Produits laitiers & Oeufs": [
        "oeuf", "beurre", "lait", "crème", "fromage", "yaourt", "mozzarella",
        "parmesan", "gruyère", "emmental", "ricotta", "mascarpone", "feta",
        "chèvre", "camembert", "brie", "crème fraîche",
    ],
    "Épicerie & Condiments": [
        "farine", "sucre", "sel", "poivre", "huile", "vinaigre", "moutarde",
        "ketchup", "mayonnaise", "sauce", "bouillon", "pâtes", "riz",
        "lentille", "haricot sec", "boîte", "conserve", "concentré",
        "tomate concassée", "lait de coco", "miel", "sirop", "confiture",
        "cornichon", "câpre", "olive", "anchois",
    ],
    "Féculents & Pains": [
        "pomme de terre", "patate", "pain", "baguette", "tortilla",
        "wrap", "tagliatelle", "spaghetti", "penne", "fusilli", "lasagne",
        "gnocchi", "quinoa", "couscous", "boulgour", "polenta",
    ],
    "Fruits": [
        "citron", "orange", "pomme", "poire", "banane", "fraise", "framboise",
        "myrtille", "cerise", "abricot", "pêche", "mangue", "ananas",
        "kiwi", "raisin", "melon", "pastèque", "avocat", "lime",
    ],
}


def _normalize_unit(unit: str) -> str:
    return _UNIT_MAP.get(unit.lower().strip(), unit.lower().strip())


def _categorize(name: str) -> str:
    name_lower = name.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return category
    return "Autres"


def _ingredient_key(name: str) -> str:
    # Normalize name for deduplication: lowercase, remove accents (basic), strip
    return re.sub(r"\s+", " ", name.lower().strip())


def build_shopping_list(recipes: list[dict], adults: int) -> dict[str, list[dict]]:
    """
    Returns a dict {category: [{"name": str, "display": str}]} sorted by category.
    Scales quantities from base_servings to adults.
    """
    aggregated: dict[str, dict] = {}  # key -> {name, unit, total_amount, raw_list}

    for recipe in recipes:
        base = recipe.get("base_servings", 2)
        scale = adults / base if base else 1.0

        for ing in recipe.get("ingredients", []):
            name = ing.get("name", "").strip()
            if not name:
                continue
            unit = _normalize_unit(ing.get("unit", ""))
            amount = ing.get("amount")

            key = f"{_ingredient_key(name)}|{unit}"

            if key not in aggregated:
                aggregated[key] = {
                    "name": name,
                    "unit": unit,
                    "total_amount": 0.0 if amount is not None else None,
                    "has_amount": amount is not None,
                    "raw_list": [],
                }

            if amount is not None:
                scaled = round(amount * scale, 1)
                if aggregated[key]["has_amount"]:
                    aggregated[key]["total_amount"] = (aggregated[key]["total_amount"] or 0) + scaled
            aggregated[key]["raw_list"].append(ing.get("raw", name))

    # Format and categorize
    by_category: dict[str, list[dict]] = defaultdict(list)
    for item in aggregated.values():
        name = item["name"]
        unit = item["unit"]
        amount = item["total_amount"]

        if amount is not None and amount > 0:
            # Format nicely: "800 g", "2 càs"
            amount_str = str(int(amount)) if amount == int(amount) else str(amount)
            display = f"{name} ({amount_str}{' ' + unit if unit else ''})"
        else:
            display = name

        category = _categorize(name)
        by_category[category].append({"name": name, "display": display})

    # Sort categories in a logical supermarket order
    order = [
        "Légumes & Herbes", "Fruits", "Viandes & Poissons",
        "Produits laitiers & Oeufs", "Féculents & Pains",
        "Épicerie & Condiments", "Autres",
    ]
    sorted_list = {}
    for cat in order:
        if cat in by_category:
            sorted_list[cat] = sorted(by_category[cat], key=lambda x: x["name"])
    for cat in by_category:
        if cat not in sorted_list:
            sorted_list[cat] = sorted(by_category[cat], key=lambda x: x["name"])

    return sorted_list
