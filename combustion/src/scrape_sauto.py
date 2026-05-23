import asyncio
import re
from pathlib import Path
import aiohttp
import pandas as pd

from utils import (
    normalize_model,
    extract_engine_volume,
    extract_engine_type,
    extract_hybrid_type,
    extract_body_type,
    extract_trim,
    extract_warranty,
    clean_extra,
)

COLS = [
    "Model auta", "Cena (Kč)", "Nájezd (km)", "Výkon (kW)", "Rok výroby",
    "Palivo", "Převodovka", "Kola", "Náhon 4x4", "Extra",
    "Objem motoru", "Typ motoru", "Hybrid typ", "Karoserie", "Výbava", "Záruka",
    "Stav", "Zdroj", "Odkaz na auto",
]

SEARCH_URL = "https://www.sauto.cz/api/v1/items/search"
DETAIL_URL = "https://www.sauto.cz/api/v1/items/{id}"
LISTING_URL = "https://www.sauto.cz/osobni/detail/{man}/{mod}/{id}"

SEARCH_PARAMS = {
    "price_to":         750000,
    "vehicle_age_from": 2021,
    "fuel_seo":         "benzin,nafta,lpg-benzin,cng-benzin",
    "tachometer_to":    100000,
    "engine_power_from": 100,
    "capacity_from":    4,
    "door_from":        5,
    "condition_seo":    "nove,ojete,predvadeci",
    "typ_seo":          "cuv,kombi,suv,hatchback,mpv",
    "category_id":      838,
    "operating_lease":  "false",
}

PAGE_SIZE = 100
DETAIL_CONCURRENCY = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

AWD_RE = re.compile(
    r'všech\s+kol|4x4|AWD|4MATIC|quattro|xDrive',
    re.IGNORECASE,
)

_EXCLUDED_FUEL_RE = re.compile(r'hybrid|elektro', re.IGNORECASE)


async def fetch_all_items(session: aiohttp.ClientSession) -> list:
    """Page through the search API and return every result item."""
    items: list = []
    offset = 0
    total = None

    while True:
        params = {**SEARCH_PARAMS, "limit": PAGE_SIZE, "offset": offset}
        async with session.get(SEARCH_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        if total is None:
            total = data["pagination"]["total"]
            print(f"  Celkem {total} inzerátů")

        batch = data["results"]
        items.extend(batch)
        offset += PAGE_SIZE

        if offset >= total or not batch:
            break

    return items


async def fetch_detail(session: aiohttp.ClientSession, item_id: int,
                       semaphore: asyncio.Semaphore) -> dict:
    """Return the 'result' dict from the item detail endpoint, or {} on error."""
    url = DETAIL_URL.format(id=item_id)
    try:
        async with semaphore:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                return data.get("result", {})
    except Exception:
        return {}


def build_record(item: dict, detail: dict) -> dict | None:
    """Combine search-API item and detail-API result into one CSV row.

    Returns None for records that should be excluded (wrong fuel, damaged).
    """
    fuel = (detail.get("fuel_cb") or {}).get("name", "")
    if _EXCLUDED_FUEL_RE.search(fuel):
        return None

    condition = (detail.get("condition_cb") or {}).get("name", "")
    if "Havarované" in condition:
        return None

    brand = item["manufacturer_cb"]["name"]
    model = item["model_cb"]["name"]
    suffix = item.get("additional_model_name") or ""

    if model == "Ostatní" and suffix:
        model_base = normalize_model(f"{brand} {suffix}")
        suffix = ""
    else:
        model_base = normalize_model(f"{brand} {model}")

    price = item.get("price") or ""
    mileage = item.get("tachometer") or ""
    year = (item.get("in_operation_date") or item.get("manufacturing_date") or "")[:4]

    engine_power = detail.get("engine_power") or ""
    drive_name = (detail.get("drive_cb") or {}).get("name", "")
    awd = "Ano" if AWD_RE.search(drive_name) else "Ne"
    gearbox = (detail.get("gearbox_cb") or {}).get("name", "")

    extra_parts = []
    if suffix:
        extra_parts.append(suffix)

    # Engine volume: API field (in cc) → litres, fallback to suffix parsing
    engine_vol_raw = detail.get("engine_volume")
    if engine_vol_raw and int(engine_vol_raw) > 100:
        engine_volume = f"{int(engine_vol_raw) / 1000:.1f}"
    elif engine_vol_raw:
        engine_volume = str(engine_vol_raw)
    else:
        engine_volume = extract_engine_volume(suffix)

    # Body type: API field, fallback to suffix parsing
    body_api = (detail.get("vehicle_body_cb") or {}).get("name", "")
    body_type = body_api if body_api else extract_body_type(model_base + " " + suffix)

    extracted = {
        "Objem motoru":  engine_volume,
        "Typ motoru":    extract_engine_type(suffix),
        "Hybrid typ":    extract_hybrid_type(suffix),
        "Karoserie":     body_type,
        "Výbava":        extract_trim(suffix),
        "Záruka":        extract_warranty(suffix),
    }

    extra_text = " / ".join(extra_parts)

    link = LISTING_URL.format(
        man=item["manufacturer_cb"]["seo_name"],
        mod=item["model_cb"]["seo_name"],
        id=item["id"],
    )

    return {
        "Model auta":    model_base,
        "Cena (Kč)":     price,
        "Nájezd (km)":   mileage,
        "Výkon (kW)":    engine_power,
        "Rok výroby":    year,
        "Palivo":        fuel,
        "Převodovka":    gearbox,
        "Kola":          "",
        "Náhon 4x4":     awd,
        "Extra":         clean_extra(extra_text, extracted),
        **extracted,
        "Stav":          condition,
        "Zdroj":         "Sauto.cz",
        "Odkaz na auto": link,
    }


async def scrape_sauto():
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        print("Načítám seznam inzerátů ze Sauto API...")
        items = await fetch_all_items(session)
        print(f"  Staženo {len(items)} položek. Načítám detaily...")

        semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
        details = await asyncio.gather(
            *[fetch_detail(session, item["id"], semaphore) for item in items]
        )

    cars = [r for r in (build_record(item, detail) for item, detail in zip(items, details)) if r is not None]

    df = pd.DataFrame(cars, columns=COLS)
    df.drop_duplicates(subset="Odkaz na auto", inplace=True)
    df.to_csv(Path(__file__).parent.parent / "data" / "scrapes" / "sauto.csv", index=False, encoding="utf-8")
    print(f"Hotovo – uloženo {len(df)} aut do sauto.csv")


if __name__ == "__main__":
    asyncio.run(scrape_sauto())
