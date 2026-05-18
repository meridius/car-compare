import asyncio
import re
import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from utils import normalize_model

URL = "https://www.energycars.cz/nabidka-vozidel/?ordering=price_asc"
DETAIL_CONCURRENCY = 5


async def load_all(page):
    """Click any 'load more' button until it disappears."""
    for label in ["Načíst další", "Zobrazit více", "Načíst více"]:
        while True:
            try:
                btn = page.locator(f'text="{label}"')
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(2000)
                else:
                    break
            except Exception:
                break


async def fetch_detail_data(browser, url, semaphore):
    """Return (tepelné_čerpadlo, kola, náhon_4x4) from a car detail page.

    Scrapes:
    - Tepelné čerpadlo: presence of the text in Výbava section
    - Kola: wheel size in inches from equipment list (e.g. '19" kola' → '19"')
    - Náhon 4x4: from the Motor table's Pohon row
    """
    try:
        async with semaphore:
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                html = await page.content()
            finally:
                await page.close()
    except Exception:
        return "Ne", "", "Ne"

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ")

    # Heat pump: literal string anywhere on the detail page
    tepelne = "Ano" if "Tepelné čerpadlo" in text else "Ne"

    # Wheel size: matches "17" kola", "19" kola", "20" kola" etc.
    kola_match = re.search(r'(\d{2})["\u201d]\s*kola', text)
    kola = f'{kola_match.group(1)}"' if kola_match else ""

    # Drive type from the Motor parameters table
    pohon = ""
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) == 2 and cells[0].get_text(strip=True) == "Pohon":
            pohon = cells[1].get_text(strip=True)
            break
    awd = "Ano" if re.search(r'4x4|všechna|AWD|quattro|xDrive|4MATIC', pohon, re.IGNORECASE) else "Ne"

    return tepelne, kola, awd


async def scrape_energycars():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"Zpracovávám: {URL}")
        await page.goto(URL)

        # Accept cookies
        for cookie_text in ["Souhlasím", "Accept all", "Přijmout vše"]:
            try:
                await page.click(f'text="{cookie_text}"', timeout=2000)
                await page.wait_for_timeout(500)
                break
            except Exception:
                pass

        await load_all(page)

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
                r'(\d{3}(?:[\s\xa0]\d{3})+)[\s\xa0]*Kč[\s\xa0]+vč\.', text
            )
            if not price_match:
                price_match = re.search(r'(\d{3}(?:[\s\xa0]\d{3})+)[\s\xa0]*Kč', text)
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
            if year:
                extra_parts.append(f"Rok {year}")

            cars.append({
                "Model auta":        model,
                "Cena (Kč)":         price,
                "Nájezd (km)":       mileage,
                "Výkon (kW)":        power,
                "Tepelné čerpadlo":  "",   # filled from detail page
                "Kola":              "",   # filled from detail page
                "Náhon 4x4":         "",   # filled from detail page
                "Extra":             " / ".join(extra_parts),
                "Zdroj":             "EnergyCars.cz",
                "Stav":              "Dostupný",
                "Odkaz na auto":     link,
            })

        # Fetch all detail pages concurrently (capped by semaphore)
        print(f"  Načítám detaily pro {len(cars)} aut...")
        semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
        detail_results = await asyncio.gather(
            *[fetch_detail_data(browser, car["Odkaz na auto"], semaphore) for car in cars]
        )
        for car, (tepelne, kola, awd) in zip(cars, detail_results):
            car["Tepelné čerpadlo"] = tepelne
            car["Kola"] = kola
            car["Náhon 4x4"] = awd

        df = pd.DataFrame(cars)
        df.drop_duplicates(subset="Odkaz na auto", inplace=True)
        df.to_csv("energycars.csv", index=False, encoding="utf-8")
        print(f"Hotovo – uloženo {len(df)} aut do energycars.csv")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(scrape_energycars())
