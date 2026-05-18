import asyncio
import re
import aiohttp
import pandas as pd

from utils import normalize_model

COLS = [
    "Model auta", "Cena (Kč)", "Nájezd (km)", "Výkon (kW)", "Rok výroby",
    "Tepelné čerpadlo", "Kola", "Náhon 4x4", "Extra", "Stav", "Zdroj", "Odkaz na auto",
]

SEARCH_URL = "https://www.sauto.cz/api/v1/items/search"
DETAIL_URL = "https://www.sauto.cz/api/v1/items/{id}"
LISTING_URL = "https://www.sauto.cz/osobni/detail/{man}/{mod}/{id}"

SEARCH_PARAMS = {
    "price_to":       750000,
    "vehicle_age_from": 2021,
    "fuel_seo":       "elektro",
    "tachometer_to":  100000,
    "capacity_from":  4,
    "door_from":      5,
    "equipment_seo":  "tepelne-cerpadlo",
    "category_id":    838,
    "operating_lease": "false",
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


def build_record(item: dict, detail: dict) -> dict:
    """Combine search-API item and detail-API result into one CSV row."""
    brand = item["manufacturer_cb"]["name"]
    model = item["model_cb"]["name"]
    model_base = normalize_model(f"{brand} {model}")

    suffix = item.get("additional_model_name") or ""
    price = item.get("price") or ""
    mileage = item.get("tachometer") or ""
    year = (item.get("in_operation_date") or "")[:4]

    engine_power = detail.get("engine_power") or ""
    battery_kw = detail.get("battery_capacity") or ""
    vehicle_range = detail.get("vehicle_range") or ""
    drive_name = (detail.get("drive_cb") or {}).get("name", "")
    awd = "Ano" if AWD_RE.search(drive_name) else "Ne"

    extra_parts = []
    if vehicle_range:
        extra_parts.append(f"Dojezd {vehicle_range} km")
    if battery_kw:
        extra_parts.append(f"Baterie {battery_kw} kWh")
    if suffix:
        extra_parts.append(suffix)

    link = LISTING_URL.format(
        man=item["manufacturer_cb"]["seo_name"],
        mod=item["model_cb"]["seo_name"],
        id=item["id"],
    )

    return {
        "Model auta":        model_base,
        "Cena (Kč)":         price,
        "Nájezd (km)":       mileage,
        "Výkon (kW)":        engine_power,
        "Rok výroby":        year,
        "Tepelné čerpadlo":  "Ano",   # guaranteed by equipment_seo filter
        "Kola":              "",
        "Náhon 4x4":         awd,
        "Extra":             " / ".join(extra_parts),
        "Stav":              "",
        "Zdroj":             "Sauto.cz",
        "Odkaz na auto":     link,
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

    cars = [build_record(item, detail) for item, detail in zip(items, details)]

    df = pd.DataFrame(cars, columns=COLS)
    df.drop_duplicates(subset="Odkaz na auto", inplace=True)
    df.to_csv("sauto.csv", index=False, encoding="utf-8")
    print(f"Hotovo – uloženo {len(df)} aut do sauto.csv")


if __name__ == "__main__":
    asyncio.run(scrape_sauto())
