import asyncio
from pathlib import Path
import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import re

from utils import normalize_model, extract_body_type, merge_with_previous

URLS = [
    ("https://www.autodraft.cz/auta.html?palivo=elektro", False),
    ("https://www.autodraft.cz/auta-na-ceste.html", True),
]

# Status keywords appear lowercase at START and END of model block in card text.
# With status:    "{status} {ModelName} {status} ocen\u00edte na cest\u00e1ch: Elektro ..."
# Without status: "{ModelName} ocen\u00edte na cest\u00e1ch: Elektro ..."
STATUS_MAP = {
    "domluven\u00e1 prohl\u00eddka": "Zamluven\u00e9",
    "z\u00e1lohovan\u00e9":          "Zamluven\u00e9",
    "zarezervovan\u00e9":             "Zamluven\u00e9",
    "prodan\u00e9":                   "Prodan\u00e9",
}

MODEL_SEPARATOR = "ocen\u00edte na cest\u00e1ch:"


def extract_model_and_status(text, is_on_the_way):
    """Extract clean model name and status label from card text."""
    text_lower = text.lower()

    if MODEL_SEPARATOR in text_lower:
        idx = text_lower.index(MODEL_SEPARATOR)
        model_block = text[:idx].strip()
    elif "Elektro" in text:
        model_block = text.split("Elektro")[0].strip()
    else:
        model_block = text.strip()

    default_status = "Chyst\u00e1 se" if is_on_the_way else "Dostupn\u00fd"
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
    """Strip nav noise and split 'VW ID.4 Pro 150kW / ALU ...' into (base_name, extra)."""
    # Remove leading navigation artefacts like "P\u0159edchoz\u00ed Dal\u0161\u00ed"
    model = re.sub(r'^(?:P\u0159edchoz\u00ed\s+|Dal\u0161\u00ed\s+)+', '', model).strip()
    m = re.search(r'\s+(\d+kW\b.*)', model, re.IGNORECASE)
    if m:
        return model[:m.start()].strip(), m.group(1).strip()
    return model, ""


COLS = [
    "Model auta", "Cena (K\u010d)", "N\u00e1jezd (km)", "V\u00fdkon (kW)", "Rok v\u00fdroby",
    "Tepeln\u00e9 \u010derpadlo", "Kola", "N\u00e1hon 4x4", "Karoserie", "Extra", "Stav", "Zdroj", "Odkaz na auto",
]


def split_extra(extra):
    """Split extra string into (power_kw, kola, nahon_4x4, rok_vyroby, remaining_extra).

    '4x4' goes to nahon_4x4; bare year (2010-2029) or MM/YYYY goes to rok_vyroby;
    'Ta\u017en\u00e9' is kept in extra; ALU/Sada go to kola.
    """
    power_match = re.match(r'^(\d+)kW\b', extra, re.IGNORECASE)
    power = power_match.group(1) if power_match else ""
    # Strip the leading " / " that separates power from the rest
    rest = re.sub(r'^\s*/\s*', '', extra[power_match.end():]).strip() if power_match else extra

    # Split only on " / " (with spaces) so that dates like "03/2030" are preserved.
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


# Extracts Enyaq variant from autodraft detail URL slug, e.g.
# ".../skoda-enyaq-iv-60-132kw..." → "iV 60"
_ENYAQ_URL_VARIANT_RE = re.compile(r'enyaq-(?:iv-?)?(80x?|60|50)', re.IGNORECASE)


def _enyaq_variant_from_url(url: str) -> str:
    """Return Enyaq variant string ('iV 50', 'iV 60', 'iV 80') from the
    autodraft detail URL slug, or '' if not found."""
    m = _ENYAQ_URL_VARIANT_RE.search(url)
    return f"iV {m.group(1)}" if m else ""


async def load_all(page):
    """Click 'Na\u010d\u00edst dal\u0161\u00ed auta' until it disappears."""
    while True:
        try:
            btn = page.locator('text="Na\u010d\u00edst dal\u0161\u00ed auta"')
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

        for url, is_on_the_way in URLS:
            print(f"Zpracov\u00e1v\u00e1m: {url}")
            await page.goto(url)

            try:
                await page.click("text=Accept all", timeout=3000)
            except Exception:
                pass

            if is_on_the_way:
                try:
                    await page.click('label:has-text("elektro")', timeout=3000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass

            await load_all(page)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            seen = set()
            for car in soup.find_all("a", href=True):
                href = car["href"]
                if "/detail/" not in href:
                    continue

                text = car.get_text(separator=" ", strip=True)

                if is_on_the_way and "Elektro" not in text:
                    continue

                model, status = extract_model_and_status(text, is_on_the_way)
                base_name, extra = split_model(model)
                base_name = normalize_model(base_name)
                power, kola, nahon_4x4, rok_vyroby, extra_rest = split_extra(extra)

                link = href if href.startswith("http") else "https://www.autodraft.cz" + href
                if link in seen:
                    continue
                seen.add(link)

                # For Enyaq cards without a variant number, extract it from the detail URL slug.
                if re.search(r'\bEnyaq\b', base_name, re.IGNORECASE) and not re.search(r'iV\s+\d', base_name):
                    variant = _enyaq_variant_from_url(link)
                    if variant:
                        base_name = f"Škoda Enyaq {variant}"

                # Price: e.g. "597 000 Kč" or "1 387 000 Kč" – groups of 3 digits.
                # Negative lookbehind prevents matching the year ("9/2022 597 000 Kč" → "2022597000" bug).
                price_match = re.search(r"(?<!\d)(\d{1,3}(?:\s\d{3})+)\s*K\u010d", text)
                price = price_match.group(1).replace(" ", "") if price_match else ""

                mileage_match = re.search(r"(?<!\d)(\d{1,3}(?:\s\d{3})+)\s*km", text)
                mileage = mileage_match.group(1).replace(" ", "") if mileage_match else ""

                # Year: listed in card as "M/YYYY" or "MM/YYYY" (e.g. "9/2022")
                year_match = re.search(r'(?<!\d)\d{1,2}/(20[12]\d)(?!\d)', text)
                rok_vyroby = year_match.group(1) if year_match else rok_vyroby

                all_cars.append({
                    "Model auta":        base_name,
                    "Cena (Kč)":         price,
                    "Nájezd (km)":       mileage,
                    "Výkon (kW)":        power,
                    "Rok výroby":        rok_vyroby,
                    "Tepelné čerpadlo":  "Ano" if "Tepelko" in text else "Ne",
                    "Kola":              kola,
                    "Náhon 4x4":         nahon_4x4,
                    "Karoserie":         extract_body_type(base_name + " " + extra_rest),
                    "Extra":             extra_rest,
                    "Stav":              status,
                    "Zdroj":             "Autodraft.cz",
                    "Odkaz na auto":     link,
                })

        df = pd.DataFrame(all_cars, columns=COLS)
        df.drop_duplicates(subset="Odkaz na auto", inplace=True)
        csv_path = Path(__file__).parent.parent / "data" / "scrapes" / "autodraft.csv"
        df = merge_with_previous(df, csv_path)
        df.to_csv(csv_path, index=False, encoding="utf-8")
        print(f"Hotovo \u2013 ulo\u017eeno {len(df)} aut do autodraft.csv")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(scrape_autodraft())
