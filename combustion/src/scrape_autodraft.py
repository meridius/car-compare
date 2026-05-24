import asyncio
from pathlib import Path
import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import re

from utils import (
    normalize_model,
    extract_engine_volume,
    extract_engine_volume_from_model,
    extract_engine_type,
    strip_engine_from_model,
    extract_hybrid_type,
    extract_body_type,
    extract_trim,
    extract_warranty,
    extract_dct,
    extract_particle_filter,
    extract_awd,
    clean_extra,
    load_authoritative_list,
    match_to_authoritative,
)

URLS = [
    ("https://www.autodraft.cz/auta.html?palivo=benzin", False, "Benzín"),
    ("https://www.autodraft.cz/auta.html?palivo=diesel", False, "Nafta"),
    ("https://www.autodraft.cz/auta-na-ceste.html", True, ""),
]

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
    """Extract clean model name and status label from card text."""
    text_lower = text.lower()

    if MODEL_SEPARATOR in text_lower:
        idx = text_lower.index(MODEL_SEPARATOR)
        model_block = text[:idx].strip()
    else:
        # Fallback: split on known fuel keywords
        model_block = text.strip()
        for kw in _FUEL_KEYWORDS:
            if kw in text:
                model_block = text.split(kw)[0].strip()
                break

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
    """Strip nav noise and split 'VW Golf 110kW / ALU ...' into (base_name, extra)."""
    model = re.sub(r'^(?:Předchozí\s+|Další\s+)+', '', model).strip()
    model = re.sub(r'^2letá záruka teď zdarma\s*', '', model).strip()
    m = re.search(r'\s+(\d+kW\b.*)', model, re.IGNORECASE)
    if m:
        return model[:m.start()].strip(), m.group(1).strip()
    return model, ""


COLS = [
    "Model auta", "Cena (Kč)", "Nájezd (km)", "Rok výroby",
    "Palivo", "Objem motoru", "Typ motoru", "Hybrid typ",
    "Výkon (kW)", "Převodovka", "Dvouspojková převodovka", "Filtr pevných částic",
    "Kola", "Náhon 4x4", "Karoserie", "Výbava", "Záruka",
    "Extra", "Stav", "Zdroj", "Odkaz na auto",
]


def split_extra(extra):
    """Split extra string into (power_kw, kola, nahon_4x4, rok_vyroby, remaining_extra)."""
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


async def load_all(page):
    """Click 'Načíst další auta' until it disappears."""
    while True:
        try:
            btn = page.locator('text="Načíst další auta"')
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(2000)
            else:
                break
        except Exception:
            break


async def scrape_autodraft():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        all_cars = []
        seen = set()

        for url, is_on_the_way, url_fuel in URLS:
            print(f"Zpracovávám: {url}")
            await page.goto(url)

            try:
                await page.click("text=Accept all", timeout=3000)
            except Exception:
                pass

            if is_on_the_way:
                # Click benzin + diesel fuel checkboxes on the coming-soon page
                for fuel_label in ["benzin", "diesel"]:
                    try:
                        await page.click(f'label:has-text("{fuel_label}")', timeout=3000)
                        await page.wait_for_timeout(1000)
                    except Exception:
                        pass

            await load_all(page)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            for car in soup.find_all("a", href=True):
                href = car["href"]
                if "/detail/" not in href:
                    continue

                text = car.get_text(separator=" ", strip=True)

                # Skip electric and hybrid cards
                if _EXCLUDED_FUEL_RE.search(text):
                    continue

                # Extract fuel type: from URL param or from card text after MODEL_SEPARATOR
                fuel = url_fuel
                text_lower = text.lower()
                if not fuel and MODEL_SEPARATOR in text_lower:
                    sep_idx = text_lower.index(MODEL_SEPARATOR)
                    after_sep = text[sep_idx + len(MODEL_SEPARATOR):].strip()
                    fuel = _extract_fuel(after_sep)

                if is_on_the_way and not fuel:
                    continue

                model, status = extract_model_and_status(text, is_on_the_way)
                base_name, extra = split_model(model)
                base_name = normalize_model(base_name)
                power, kola, nahon_4x4, rok_vyroby, extra_rest = split_extra(extra)

                link = href if href.startswith("http") else "https://www.autodraft.cz" + href
                if link in seen:
                    continue
                seen.add(link)

                transmission = _extract_transmission(text)

                price_match = re.search(r"(?<!\d)(\d{1,3}(?:\s\d{3})+)\s*Kč", text)
                price = price_match.group(1).replace(" ", "") if price_match else ""

                mileage_match = re.search(r"(?<!\d)(\d{1,3}(?:\s\d{3})+)\s*km", text)
                mileage = mileage_match.group(1).replace(" ", "") if mileage_match else ""

                year_match = re.search(r'(?<!\d)\d{1,2}/(20[12]\d)(?!\d)', text)
                rok_vyroby = year_match.group(1) if year_match else rok_vyroby

                # 4x4/AWD from extra text overrides split_extra result
                if extract_awd(extra_rest) == "Ano":
                    nahon_4x4 = "Ano"
                # Also check base_name for AWD indicators
                if nahon_4x4 == "Ne" and extract_awd(base_name) == "Ano":
                    nahon_4x4 = "Ano"

                # Extract engine vol/type from model name (primary), fallback to extra_rest
                engine_vol = extract_engine_volume_from_model(base_name) or extract_engine_volume(extra_rest)
                engine_type = extract_engine_type(base_name) or extract_engine_type(extra_rest)

                # Strip engine info from model name
                base_name = strip_engine_from_model(base_name,
                    extract_engine_volume_from_model(base_name),
                    extract_engine_type(base_name))

                # Extract trim from both base_name and extra_rest
                trim = extract_trim(base_name) or extract_trim(extra_rest)

                extracted = {
                    "Objem motoru":  engine_vol,
                    "Typ motoru":    engine_type,
                    "Hybrid typ":    extract_hybrid_type(text),
                    "Karoserie":     extract_body_type(base_name + " " + extra_rest),
                    "Výbava":        trim,
                    "Záruka":        extract_warranty(text),
                    "Dvouspojková převodovka": extract_dct(text),
                    "Filtr pevných částic":    extract_particle_filter(extra_rest),
                }

                all_cars.append({
                    "Model auta":    base_name,
                    "Cena (Kč)":     price,
                    "Nájezd (km)":   mileage,
                    "Výkon (kW)":    power,
                    "Rok výroby":    rok_vyroby,
                    "Palivo":        fuel,
                    "Převodovka":    transmission,
                    "Kola":          kola,
                    "Náhon 4x4":     nahon_4x4,
                    "Extra":         clean_extra(extra_rest, extracted),
                    **extracted,
                    "Stav":          status,
                    "Zdroj":         "Autodraft.cz",
                    "Odkaz na auto": link,
                })

        df = pd.DataFrame(all_cars, columns=COLS)
        df.drop_duplicates(subset="Odkaz na auto", inplace=True)
        df.sort_values("Odkaz na auto", inplace=True)
        auth = load_authoritative_list(Path(__file__).parent.parent / "data" / "makes-and-models.csv")
        df = match_to_authoritative(df, auth)
        df.to_csv(Path(__file__).parent.parent / "data" / "scrapes" / "autodraft.csv", index=False, encoding="utf-8")
        print(f"Hotovo – uloženo {len(df)} aut do autodraft.csv")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(scrape_autodraft())
