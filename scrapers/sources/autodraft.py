"""Autodraft.cz adapter — both EV and ICE listings via Playwright + BeautifulSoup."""
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from scrapers.core import browser, schema
from scrapers.core.normalize import normalize_model
from scrapers.core.fields import (
    extract_body_type, extract_engine_volume, extract_engine_volume_from_model,
    extract_engine_type, strip_engine_from_model, extract_hybrid_type, extract_trim,
    extract_warranty, extract_dct, extract_particle_filter, extract_awd, clean_extra,
)

SOURCE_NAME = "Autodraft.cz"
SOURCE_SLUG = "autodraft"
FUELS = {"EV", "ICE"}

# Each tuple: (url, is_on_the_way, kind, url_fuel)
# kind: "EV" = electric list page, "ICE" = combustion list page, "BOTH" = coming-soon (mixed)
# url_fuel: pre-determined fuel string for ICE list pages; "" means detect from card text.
URLS = [
    ("https://www.autodraft.cz/auta.html?palivo=elektro", False, "EV", ""),
    ("https://www.autodraft.cz/auta.html?palivo=benzin", False, "ICE", "Benzín"),
    ("https://www.autodraft.cz/auta.html?palivo=diesel", False, "ICE", "Nafta"),
    ("https://www.autodraft.cz/auta-na-ceste.html", True, "BOTH", ""),
]
LOAD_MORE = ["Načíst další auta"]
COOKIE_TEXTS = ["Accept all"]

STATUS_MAP = {
    "domluvená prohlídka": "Zamluvené",
    "zálohované":          "Zamluvené",
    "zarezervované":       "Zamluvené",
    "prodané":             "Prodané",
}

MODEL_SEPARATOR = "oceníte na cestách:"

# Fuel keywords appearing after MODEL_SEPARATOR — used to detect fuel type
# and as a fallback model/spec boundary.
_FUEL_KEYWORDS = [
    "LPG + benzín", "CNG + benzín",
    "Benzín", "Nafta", "Diesel", "LPG", "CNG",
]
_EXCLUDED_FUEL_RE = re.compile(r'\b(?:Elektro|Hybrid)\b', re.IGNORECASE)

_TRANSMISSION_RE = re.compile(
    r'\b(automat(?:ick[áa])?|DSG|manu[áa]l(?:ní)?|Man\.|MAN)\b', re.IGNORECASE,
)

_ENYAQ_URL_VARIANT_RE = re.compile(r'enyaq-(?:iv-?)?(80x?|60|50)', re.IGNORECASE)


# --- VERBATIM ports from combustion/src/scrape_autodraft.py ---

def _extract_fuel(text_after_sep: str) -> str:
    """Extract fuel type from text appearing after MODEL_SEPARATOR."""
    for kw in _FUEL_KEYWORDS:
        if text_after_sep.lower().startswith(kw.lower()):
            return kw
    return ""


def _extract_transmission(text: str) -> str:
    """Extract transmission type from card text."""
    m = _TRANSMISSION_RE.search(text)
    if not m:
        return ""
    raw = m.group(1)
    if raw.lower().startswith("auto") or raw.lower() == "dsg":
        return "Automat"
    return "Manual"


def extract_model_and_status(text, is_on_the_way):
    """Extract clean model name and status label from card text.

    Fallback boundary detection:
    - Combustion: splits on first known fuel keyword when MODEL_SEPARATOR absent.
    - Electric: splits on "Elektro" when MODEL_SEPARATOR and fuel keywords both absent.
    Both originals are merged so this one function serves all routing paths.
    """
    text_lower = text.lower()

    if MODEL_SEPARATOR in text_lower:
        idx = text_lower.index(MODEL_SEPARATOR)
        model_block = text[:idx].strip()
    else:
        # Combustion fallback: split on first fuel keyword in the card text
        model_block = text.strip()
        for kw in _FUEL_KEYWORDS:
            if kw in text:
                model_block = text.split(kw)[0].strip()
                break
        else:
            # Electric-only fallback: split on "Elektro" (not in _FUEL_KEYWORDS)
            if "Elektro" in text:
                model_block = text.split("Elektro")[0].strip()

    default_status = "Chystá se" if is_on_the_way else "Dostupný"
    status = default_status
    model = model_block

    for sw, mapped in STATUS_MAP.items():
        if model_block.lower().startswith(sw):
            status = mapped
            rest = model_block[len(sw):].strip()
            if rest.lower().endswith(sw):
                rest = rest[: -len(sw)].strip()
            model = rest
            break

    return model.strip(), status


def split_model(model):
    """Strip nav noise and split 'VW Golf 110kW / ALU ...' into (base_name, extra).

    Verbatim from combustion/src/scrape_autodraft.py (superset: also strips
    '2letá záruka teď zdarma' prefix that electric never needed).
    """
    model = re.sub(r'^(?:Předchozí\s+|Další\s+)+', '', model).strip()
    model = re.sub(r'^2letá záruka teď zdarma\s*', '', model).strip()
    m = re.search(r'\s+(\d+kW\b.*)', model, re.IGNORECASE)
    if m:
        return model[:m.start()].strip(), m.group(1).strip()
    return model, ""


def split_extra(extra):
    """Split extra string into (power_kw, kola, nahon_4x4, rok_vyroby, remaining_extra).

    Verbatim from combustion/src/scrape_autodraft.py (identical to electric version).
    """
    power_match = re.match(r'^(\d+)kW\b', extra, re.IGNORECASE)
    power = power_match.group(1) if power_match else ""
    rest = re.sub(r'^\s*/\s*', '', extra[power_match.end():]).strip() if power_match else extra

    segments = [s.strip() for s in re.split(r'\s+/\s+', rest) if s.strip()]

    kola_parts, other_parts, nahon_4x4, rok_vyroby = [], [], "Ne", ""
    for seg in segments:
        if re.search(r'\bALU\b|\bSada\s+\d', seg, re.IGNORECASE):
            kola_parts.append(seg)
        elif seg == "4x4":
            nahon_4x4 = "Ano"
        elif re.fullmatch(r'20[12]\d', seg):
            rok_vyroby = seg
        elif re.fullmatch(r'\d{1,2}/20[12]\d', seg):
            rok_vyroby = seg[-4:]
        else:
            other_parts.append(seg)

    return power, " / ".join(kola_parts), nahon_4x4, rok_vyroby, " / ".join(other_parts)


# --- EV-only helper ---

def _enyaq_variant_from_url(url: str) -> str:
    """Return Enyaq variant string ('iV 50', 'iV 60', 'iV 80') from the
    autodraft detail URL slug, or '' if not found."""
    m = _ENYAQ_URL_VARIANT_RE.search(url)
    return f"iV {m.group(1)}" if m else ""


# --- Row builders ---

def _build_ev(text, base_name, power, kola, nahon_4x4, rok, extra_rest, status, link):
    """Build a canonical EV row (port of electric/src/scrape_autodraft.py logic)."""
    # Enyaq-from-URL recovery: variant number often absent from card text.
    if re.search(r'\bEnyaq\b', base_name, re.IGNORECASE) and not re.search(r'iV\s+\d', base_name):
        v = _enyaq_variant_from_url(link)
        if v:
            base_name = f"Škoda Enyaq {v}"
    row = schema.blank_row()
    row.update({
        "Typ": schema.TYP_EV, "Model auta": base_name, "Výkon (kW)": power,
        "Rok výroby": rok, "Palivo": "Elektro",
        "Tepelné čerpadlo": "Ano" if "Tepelko" in text else "Ne",
        "Kola": kola, "Náhon 4x4": nahon_4x4,
        "Karoserie": extract_body_type(base_name + " " + extra_rest),
        "Extra": extra_rest, "Stav": status, "Země": "Česko",
        "Zdroj": SOURCE_NAME, "Odkaz na auto": link,
    })
    return row, base_name


def _build_ice(text, base_name, power, kola, nahon_4x4, rok, extra_rest, status, link, fuel):
    """Build a canonical ICE row (port of combustion/src/scrape_autodraft.py logic)."""
    # AWD override from extra_rest and base_name (both checked, per original)
    if extract_awd(extra_rest) == "Ano" or extract_awd(base_name) == "Ano":
        nahon_4x4 = "Ano"
    # Extract engine info from model name first, fall back to extra_rest
    engine_vol = extract_engine_volume_from_model(base_name) or extract_engine_volume(extra_rest)
    engine_type = extract_engine_type(base_name) or extract_engine_type(extra_rest)
    # Strip extracted engine info from model name
    base_name = strip_engine_from_model(base_name,
        extract_engine_volume_from_model(base_name), extract_engine_type(base_name))
    trim = extract_trim(base_name) or extract_trim(extra_rest)
    extracted = {
        "Objem motoru": engine_vol,
        "Typ motoru": engine_type,
        "Hybrid typ": extract_hybrid_type(text),
        "Karoserie": extract_body_type(base_name + " " + extra_rest),
        "Verze": trim,
        "Záruka": extract_warranty(text),
        "Dvouspojková převodovka": extract_dct(text),
        "Filtr pevných částic": extract_particle_filter(extra_rest),
    }
    row = schema.blank_row()
    row.update({
        "Typ": schema.TYP_ICE, "Model auta": base_name, "Výkon (kW)": power,
        "Rok výroby": rok, "Palivo": fuel, "Převodovka": _extract_transmission(text),
        "Kola": kola, "Náhon 4x4": nahon_4x4,
        "Extra": clean_extra(extra_rest, extracted),
        "Stav": status, "Země": "Česko",
        "Zdroj": SOURCE_NAME, "Odkaz na auto": link, **extracted,
    })
    return row


async def scrape():
    rows, seen = [], set()
    async with async_playwright() as p:
        page = await (await p.chromium.launch(headless=True)).new_page()
        for url, is_on_the_way, kind, url_fuel in URLS:
            print(f"Zpracovávám: {url}")
            await page.goto(url)
            await browser.accept_cookies(page, COOKIE_TEXTS)
            if is_on_the_way:
                # Coming-soon page: click all three fuel checkboxes so both EV and ICE
                # cards load. Old electric clicked only "elektro"; old combustion clicked
                # "benzin" + "diesel". Unified clicks all three.
                for lbl in ["elektro", "benzin", "diesel"]:
                    try:
                        await page.click(f'label:has-text("{lbl}")', timeout=3000)
                        await page.wait_for_timeout(1000)
                    except Exception:
                        pass
            await browser.load_all(page, LOAD_MORE)
            soup = BeautifulSoup(await page.content(), "html.parser")

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/detail/" not in href:
                    continue
                text = a.get_text(separator=" ", strip=True)
                link = href if href.startswith("http") else "https://www.autodraft.cz" + href
                if link in seen:
                    continue

                # Determine if this card is an EV listing
                is_ev = "Elektro" in text
                is_excluded = bool(_EXCLUDED_FUEL_RE.search(text))

                # Determine fuel for ICE cards from URL param or card text
                fuel = url_fuel
                tl = text.lower()
                if not fuel and MODEL_SEPARATOR in tl:
                    after = text[tl.index(MODEL_SEPARATOR) + len(MODEL_SEPARATOR):].strip()
                    fuel = _extract_fuel(after)

                # Routing / filtering per page kind
                if kind == "EV":
                    # Electric list page is already fuel-filtered — all cards are EV
                    pass
                elif kind == "ICE":
                    # Combustion list page: skip Elektro/Hybrid cards
                    if is_excluded:
                        continue
                else:  # BOTH (coming-soon): route per card
                    # Skip ICE cards that contain Elektro/Hybrid and lack a fuel keyword,
                    # and skip cards with no fuel at all (unclassifiable)
                    if not is_ev and is_excluded:
                        continue
                    if not is_ev and not fuel:
                        continue

                model, status = extract_model_and_status(text, is_on_the_way)
                base_name, extra = split_model(model)
                base_name = normalize_model(base_name)
                power, kola, nahon_4x4, rok, extra_rest = split_extra(extra)

                price_m = re.search(r"(?<!\d)(\d{1,3}(?:\s\d{3})+)\s*Kč", text)
                mileage_m = re.search(r"(?<!\d)(\d{1,3}(?:\s\d{3})+)\s*km", text)
                year_m = re.search(r'(?<!\d)\d{1,2}/(20[12]\d)(?!\d)', text)
                if year_m:
                    rok = year_m.group(1)

                # Route to EV builder for the electric list page OR EV-flagged BOTH cards
                route_ev = (kind == "EV") or (kind == "BOTH" and is_ev)
                if route_ev:
                    row, base_name = _build_ev(text, base_name, power, kola, nahon_4x4, rok,
                                               extra_rest, status, link)
                else:
                    row = _build_ice(text, base_name, power, kola, nahon_4x4, rok,
                                     extra_rest, status, link, fuel)

                row["Cena (Kč)"] = price_m.group(1).replace(" ", "") if price_m else ""
                row["Nájezd (km)"] = mileage_m.group(1).replace(" ", "") if mileage_m else ""
                seen.add(link)
                rows.append(row)
    return rows
