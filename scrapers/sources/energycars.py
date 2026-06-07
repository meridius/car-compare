"""EnergyCars.cz adapter — EV-only listings via Playwright + BeautifulSoup."""
import asyncio
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from scrapers.core import browser, schema
from scrapers.core.normalize import normalize_model
from scrapers.core.fields import extract_body_type

SOURCE_NAME = "EnergyCars.cz"
SOURCE_SLUG = "energycars"
FUELS = {"EV"}

URL = "https://www.energycars.cz/nabidka-vozidel/?ordering=price_asc"
DETAIL_CONCURRENCY = 5


async def fetch_detail_data(browser_obj, url, semaphore):
    """Return (tepelné_čerpadlo, kola, náhon_4x4, detail_model, price) from a car detail page.

    Scrapes:
    - Tepelné čerpadlo: presence of the text in Výbava section
    - Kola: wheel size in inches from equipment list (e.g. '19" kola' → '19"')
    - Náhon 4x4: from the Motor table's Pohon row
    - detail_model: normalised model name from page H1 (used to refine ambiguous listing names)
    - price: from the .price-row-vat element (more reliable than listing card for 7-digit prices)
    """
    try:
        async with semaphore:
            page = await browser_obj.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                html = await page.content()
            finally:
                await page.close()
    except Exception:
        return "Ne", "", "Ne", "", ""

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ")

    # Heat pump: literal string anywhere on the detail page
    tepelne = "Ano" if "Tepelné čerpadlo" in text else "Ne"

    # Wheel size: matches "17" kola", "19" kola", "20" kola" etc.
    kola_match = re.search(r'(\d{2})["”]\s*kola', text)
    kola = f'{kola_match.group(1)}"' if kola_match else ""

    # Drive type from the Motor parameters table
    pohon = ""
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) == 2 and cells[0].get_text(strip=True) == "Pohon":
            pohon = cells[1].get_text(strip=True)
            break
    awd = "Ano" if re.search(r'4x4|všechna|AWD|quattro|xDrive|4MATIC', pohon, re.IGNORECASE) else "Ne"

    # Extract model name from H1 for disambiguation of ambiguous listing names
    detail_model = ""
    h1 = soup.find("h1")
    if h1:
        detail_model = normalize_model(h1.get_text(strip=True))

    # Price from structured element — more reliable than listing card text
    price = ""
    price_el = soup.find(class_="price-row-vat")
    if price_el:
        price_text = price_el.get_text(strip=True)
        price_match = re.search(r'(\d{1,3}(?:[\s\xa0]\d{3})+)', price_text)
        if price_match:
            price = re.sub(r'[\s\xa0]', '', price_match.group(1))

    return tepelne, kola, awd, detail_model, price


async def scrape():
    """Scrape EnergyCars.cz and return a list of canonical row dicts."""
    async with async_playwright() as p:
        browser_obj = await p.chromium.launch(headless=True)
        page = await browser_obj.new_page()

        print(f"Zpracovávám: {URL}")
        await page.goto(URL)

        await browser.accept_cookies(page, ["Souhlasím", "Accept all", "Přijmout vše"])

        await browser.load_all(page, ["Načíst další", "Zobrazit více", "Načíst více"])

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        cars = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/vuz/" not in href:
                continue

            link = href if href.startswith("http") else "https://www.energycars.cz" + href
            if link in seen:
                continue
            seen.add(link)

            text = a.get_text(separator=" ", strip=True)

            # Skip stubs without meaningful car data
            if "V provozu" not in text and "Nájezd" not in text:
                continue

            # Model name: everything before "V provozu od YYYY"
            model_match = re.match(r'^(.+?)\s+V provozu', text)
            if model_match:
                model = model_match.group(1).strip()
            elif "Nájezd" in text:
                model = text.split("Nájezd")[0].strip()
            else:
                continue
            if not model:
                continue

            model = normalize_model(model)

            # Price incl. VAT – prefer "X Kč vč. DPH", fall back to first Kč group
            # Groups of 3 digits separated by spaces/nbsp, minimum 6 digits total (≥ 100 000 Kč)
            price_match = re.search(
                r'(\d{1,3}(?:[\s\xa0]\d{3})+)[\s\xa0]*Kč[\s\xa0]+vč\.', text
            )
            if not price_match:
                price_match = re.search(r'(\d{1,3}(?:[\s\xa0]\d{3})+)[\s\xa0]*Kč', text)
            price = re.sub(r'[\s\xa0]', '', price_match.group(1)) if price_match else ""

            # Mileage
            mileage_match = re.search(r'Nájezd[\s\xa0]+([\d][\d\s\xa0]*)[\s\xa0]*km', text)
            mileage = re.sub(r'[\s\xa0]', '', mileage_match.group(1)).strip() if mileage_match else ""

            # Power kW
            power_match = re.search(r'Výkon[\s\xa0]+(\d+)[\s\xa0]*kW', text)
            power = power_match.group(1) if power_match else ""

            # Range km → Extra
            range_match = re.search(r'Dojezd[\s\xa0]+(\d+)[\s\xa0]*km', text)
            range_km = range_match.group(1) if range_match else ""

            # Battery capacity → Extra
            battery_match = re.search(r'Kapacita[\s\xa0]+baterie[\s\xa0]+([\d,\.]+)[\s\xa0]*kWh', text)
            battery_kwh = battery_match.group(1) if battery_match else ""

            # Year in service → Extra
            year_match = re.search(r'V provozu od[\s\xa0]+(\d{4})', text)
            year = year_match.group(1) if year_match else ""

            extra_parts = []
            if range_km:
                extra_parts.append(f"Dojezd {range_km} km")
            if battery_kwh:
                extra_parts.append(f"Baterie {battery_kwh} kWh")

            row = schema.blank_row()
            row.update({
                "Typ":              schema.TYP_EV,
                "Model auta":       model,
                "Cena (Kč)":        price,
                "Nájezd (km)":      mileage,
                "Výkon (kW)":       power,
                "Rok výroby":       year,
                "Tepelné čerpadlo": "",   # filled from detail page
                "Kola":             "",   # filled from detail page
                "Náhon 4x4":        "",   # filled from detail page
                "Karoserie":        extract_body_type(model),
                "Palivo":           "Elektro",
                "Extra":            " / ".join(extra_parts),
                "Stav":             "Dostupný",
                "Zdroj":            SOURCE_NAME,
                "Odkaz na auto":    link,
            })
            cars.append(row)

        # Fetch all detail pages concurrently (capped by semaphore)
        print(f"  Načítám detaily pro {len(cars)} aut...")
        semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
        detail_results = await asyncio.gather(
            *[fetch_detail_data(browser_obj, car["Odkaz na auto"], semaphore) for car in cars]
        )
        for car, (tepelne, kola, awd, detail_model, detail_price) in zip(cars, detail_results):
            car["Tepelné čerpadlo"] = tepelne
            car["Kola"] = kola
            car["Náhon 4x4"] = awd
            if detail_price:
                car["Cena (Kč)"] = detail_price
            # If the detail page H1 gives a longer, more specific model name that
            # starts with the same prefix as what we parsed from the listing, prefer it.
            if detail_model and detail_model.startswith(car["Model auta"]) and len(detail_model) > len(car["Model auta"]):
                car["Model auta"] = detail_model

        await browser_obj.close()
        return cars
