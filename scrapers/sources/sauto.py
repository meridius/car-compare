"""Sauto.cz adapter — both EV and ICE listings via the JSON search API."""
import re
import aiohttp

from scrapers.core import http, schema
from scrapers.core.normalize import normalize_model
from scrapers.core.fields import (
    extract_body_type, extract_engine_volume, extract_engine_type,
    extract_hybrid_type, extract_trim, extract_warranty, extract_dct,
    extract_particle_filter, extract_awd, clean_extra,
)

SOURCE_NAME = "Sauto.cz"
SOURCE_SLUG = "sauto"
FUELS = {"EV", "ICE"}

SEARCH_URL = "https://www.sauto.cz/api/v1/items/search"
DETAIL_URL = "https://www.sauto.cz/api/v1/items/{id}"
LISTING_URL = "https://www.sauto.cz/osobni/detail/{man}/{mod}/{id}"

_BASE_PARAMS = {
    "price_to": 750000, "vehicle_age_from": 2021, "tachometer_to": 100000,
    "capacity_from": 4, "door_from": 5, "category_id": 838, "operating_lease": "false",
}
EV_PARAMS = {**_BASE_PARAMS, "fuel_seo": "elektro", "equipment_seo": "tepelne-cerpadlo"}
ICE_PARAMS = {**_BASE_PARAMS, "fuel_seo": "benzin,nafta,lpg-benzin,cng-benzin",
              "engine_power_from": 100, "condition_seo": "nove,ojete,predvadeci",
              "typ_seo": "cuv,kombi,suv,hatchback,mpv"}

AWD_RE = re.compile(r'všech\s+kol|4x4|AWD|4MATIC|quattro|xDrive', re.IGNORECASE)
_EXCLUDED_FUEL_RE = re.compile(r'hybrid|elektro', re.IGNORECASE)
_ENYAQ_VARIANT_RE = re.compile(r'\biV\s*(80x?|60|50)\b|\b(80x?|60|50)\b', re.IGNORECASE)

# sauto sometimes returns model_cb "Ostatní" for models its catalog has not
# indexed yet (e.g. a just-launched EV). The real model is then buried in
# additional_model_name as a dealer-typed project code / trim string, which
# otherwise produces a garbage "Model auta" that no reference entry can match.
# Recover known cases so these cars still get backed by the reference list.
_OSTATNI_RECOVERY = [
    # Kia EV2 Standard Range: project code "QV1" or its unique 42.2 kWh battery.
    (lambda brand, s: brand == "Kia" and ("QV1" in s.upper() or bool(re.search(r'42[.,]2', s))),
     "Kia EV2"),
]


def _recover_ostatni_model(brand: str, suffix: str) -> str:
    """Map a sauto 'Ostatní' listing to a clean model name, or '' if unknown."""
    for predicate, name in _OSTATNI_RECOVERY:
        if predicate(brand, suffix):
            return name
    return ""


def _enyaq_variant(suffix):
    m = _ENYAQ_VARIANT_RE.search(suffix)
    if m:
        return f"iV {(m.group(1) or m.group(2)).lower()}"
    return ""


def _listing_link(item):
    return LISTING_URL.format(man=item["manufacturer_cb"]["seo_name"],
                              mod=item["model_cb"]["seo_name"], id=item["id"])


def _common(item):
    """Return (model_base, suffix, price, mileage, year) shared by both fuels."""
    brand = item["manufacturer_cb"]["name"]
    model = item["model_cb"]["name"]
    suffix = item.get("additional_model_name") or ""
    if model == "Ostatní" and suffix:
        recovered = _recover_ostatni_model(brand, suffix)
        model_base = recovered or normalize_model(f"{brand} {suffix}")
        suffix = ""
    else:
        model_base = normalize_model(f"{brand} {model}")
    price = item.get("price") or ""
    mileage = item.get("tachometer") or ""
    year = (item.get("in_operation_date") or item.get("manufacturing_date") or "")[:4]
    return model_base, suffix, price, mileage, year


def build_ev(item, detail):
    """EV canonical row (port of electric/src/scrape_sauto.py build_record)."""
    if not detail:
        return None
    model_base, suffix, price, mileage, year = _common(item)
    battery_kw = detail.get("battery_capacity") or ""
    vehicle_range = detail.get("vehicle_range") or ""
    if re.search(r'\bEnyaq\b', model_base, re.IGNORECASE) and suffix:
        v = _enyaq_variant(suffix)
        if v:
            model_base = f"Škoda Enyaq {v}"
    if re.fullmatch(r'Škoda Enyaq(?: iV)?', model_base) and battery_kw:
        try:
            bc = float(str(battery_kw).replace(",", "."))
            model_base = f"Škoda Enyaq {'iV 50' if bc <= 56 else 'iV 60' if bc <= 65 else 'iV 80'}"
        except ValueError:
            pass
    drive_name = (detail.get("drive_cb") or {}).get("name", "")
    body_api = (detail.get("vehicle_body_cb") or {}).get("name", "")
    extra_parts = []
    if vehicle_range:
        extra_parts.append(f"Dojezd {vehicle_range} km")
    if battery_kw:
        extra_parts.append(f"Baterie {battery_kw} kWh")
    if suffix:
        extra_parts.append(suffix)

    row = schema.blank_row()
    row.update({
        "Typ": schema.TYP_EV,
        "Model auta": model_base, "Cena (Kč)": price, "Nájezd (km)": mileage,
        "Výkon (kW)": detail.get("engine_power") or "", "Rok výroby": year,
        "Palivo": "Elektro", "Tepelné čerpadlo": "Ano",
        "Náhon 4x4": "Ano" if AWD_RE.search(drive_name) else "Ne",
        "Karoserie": body_api or extract_body_type(model_base),
        "Extra": " / ".join(extra_parts),
        "Stav": (detail.get("condition_cb") or {}).get("name", ""),
        "Zdroj": SOURCE_NAME, "Odkaz na auto": _listing_link(item),
    })
    return row


def build_ice(item, detail):
    """ICE canonical row (port of combustion/src/scrape_sauto.py build_record)."""
    if not detail:
        return None
    fuel = (detail.get("fuel_cb") or {}).get("name", "")
    if _EXCLUDED_FUEL_RE.search(fuel):
        return None
    condition = (detail.get("condition_cb") or {}).get("name", "")
    if "Havarované" in condition:
        return None
    model_base, suffix, price, mileage, year = _common(item)
    drive_name = (detail.get("drive_cb") or {}).get("name", "")
    awd = "Ano" if AWD_RE.search(drive_name) else "Ne"
    if awd == "Ne" and extract_awd(suffix) == "Ano":
        awd = "Ano"
    gearbox = (detail.get("gearbox_cb") or {}).get("name", "")

    raw = detail.get("engine_volume")
    if raw and int(raw) > 100:
        engine_volume = f"{int(raw) / 1000:.1f}"
    elif raw:
        engine_volume = str(raw)
    else:
        engine_volume = extract_engine_volume(suffix)
    body_api = (detail.get("vehicle_body_cb") or {}).get("name", "")
    body_type = body_api or extract_body_type(model_base + " " + suffix)
    extra_text = suffix if suffix else ""

    extracted = {
        "Objem motoru": engine_volume,
        "Typ motoru": extract_engine_type(suffix),
        "Hybrid typ": extract_hybrid_type(suffix),
        "Karoserie": body_type,
        "Výbava": extract_trim(suffix),
        "Záruka": extract_warranty(suffix),
        "Dvouspojková převodovka": extract_dct(gearbox + " " + suffix + " " + extra_text),
        "Filtr pevných částic": extract_particle_filter(suffix),
    }
    row = schema.blank_row()
    row.update({
        "Typ": schema.TYP_ICE,
        "Model auta": model_base, "Cena (Kč)": price, "Nájezd (km)": mileage,
        "Výkon (kW)": detail.get("engine_power") or "", "Rok výroby": year,
        "Palivo": fuel, "Převodovka": gearbox, "Náhon 4x4": awd,
        "Extra": clean_extra(extra_text, extracted),
        "Stav": condition, "Zdroj": SOURCE_NAME, "Odkaz na auto": _listing_link(item),
        **extracted,
    })
    return row


async def _scrape_fuel(session, params, builder):
    items = await http.fetch_all_items(session, SEARCH_URL, params)
    print(f"  Staženo {len(items)} položek. Načítám detaily...")
    urls = [DETAIL_URL.format(id=it["id"]) for it in items]
    details = await http.fetch_all_details(session, urls)
    return [r for r in (builder(it, d) for it, d in zip(items, details)) if r is not None]


async def scrape():
    async with aiohttp.ClientSession(headers=http.DEFAULT_HEADERS) as session:
        print("Načítám EV inzeráty ze Sauto API...")
        ev = await _scrape_fuel(session, EV_PARAMS, build_ev)
        print("Načítám ICE inzeráty ze Sauto API...")
        ice = await _scrape_fuel(session, ICE_PARAMS, build_ice)
    return ev + ice
