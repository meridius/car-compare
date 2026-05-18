import asyncio
import re
import pandas as pd
from bs4 import BeautifulSoup, NavigableString
from playwright.async_api import async_playwright

from utils import normalize_model

COLS = [
    "Model auta", "Cena (Kč)", "Nájezd (km)", "Výkon (kW)", "Rok výroby",
    "Tepelné čerpadlo", "Kola", "Náhon 4x4", "Extra", "Stav", "Zdroj", "Odkaz na auto",
]

BASE_URL = (
    "https://www.sauto.cz/inzerce/osobni"
    "?cena-do=750000"
    "&vyrobeno-od=2021"
    "&km-do=100000"
    "&pocet-mist-od=4"
    "&pocet-dveri-od=5"
    "&stav=vse"
    "&palivo=elektro"
    "&vybava=tepelne-cerpadlo"
)

DETAIL_CONCURRENCY = 5

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def accept_consent(page):
    """Accept the Seznam.cz CMP consent dialog rendered inside a shadow DOM."""
    try:
        await page.evaluate("""
            () => {
                for (const el of document.querySelectorAll('*')) {
                    if (!el.shadowRoot) continue;
                    for (const btn of el.shadowRoot.querySelectorAll('button')) {
                        const cls = btn.className || '';
                        const txt = btn.textContent.trim();
                        if (cls.includes('cw-btn--primary') &&
                            (txt === 'Agree' || txt === 'Souhlasím')) {
                            btn.click();
                            return true;
                        }
                    }
                }
                return false;
            }
        """)
        await page.wait_for_timeout(3000)
    except Exception:
        pass


def parse_listing_items(soup):
    """Extract car records from a listing page, skipping Doporučené inzeráty."""
    cars = []

    for item in soup.find_all("li"):
        classes = " ".join(item.get("class", []))
        if "c-item" not in classes or "c-preferred-list" in classes:
            continue

        link_el = item.find("a", class_="c-item__link")
        if not link_el:
            continue
        href = link_el.get("href", "")
        if not href or "/detail/" not in href:
            continue

        # Model: direct text nodes of c-item__name (exclude the suffix span)
        name_el = link_el.find("span", class_="c-item__name")
        if not name_el:
            continue
        suffix_el = name_el.find("span", class_="c-item__name--suffix")
        suffix = suffix_el.get_text(strip=True) if suffix_el else ""
        model_base = "".join(
            c for c in name_el.children if isinstance(c, NavigableString)
        ).strip().rstrip(",").strip()
        model_base = normalize_model(model_base)

        # Power: first "NNN kW" in suffix (e.g. "150 kW, IQ, ...")
        power_match = re.match(r'^(\d+)\s*kW\b\s*,?\s*', suffix, re.IGNORECASE)
        power = power_match.group(1) if power_match else ""
        suffix_rest = suffix[power_match.end():].strip() if power_match else suffix

        # ALU wheel size from suffix, e.g. '19" ALU' or 'ALU 19"'
        kola_match = re.search(r'(\d{2})["\u201d]\s*(?:ALU|kola)|ALU\s*(\d{2})["\u201d]',
                               suffix_rest, re.IGNORECASE)
        kola = ""
        if kola_match:
            inch = kola_match.group(1) or kola_match.group(2)
            kola = f'{inch}"'

        # Price: strip non-breaking spaces and extract digits
        price = ""
        price_el = item.find(class_="c-item__price")
        if price_el:
            m = re.search(r'([\d\s\xa0]+)\s*Kč', price_el.get_text(strip=True))
            if m:
                price = re.sub(r'[\s\xa0]', '', m.group(1))

        # Year + mileage from c-item__info (first line before fuel/gearbox spans)
        year, mileage = "", ""
        info_el = item.find(class_="c-item__info")
        if info_el:
            # Use only the direct text (exclude mobile-variant spans)
            info_text = "".join(
                c for c in info_el.children if isinstance(c, NavigableString)
            ).strip()
            year_m = re.match(r'^(\d{4})', info_text)
            if year_m:
                year = year_m.group(1)
            km_m = re.search(r'([\d\s\xa0]+)\s*km', info_text)
            if km_m:
                mileage = re.sub(r'[\s\xa0]', '', km_m.group(1))

        cars.append({
            "Model auta":        model_base,
            "Cena (Kč)":         price,
            "Nájezd (km)":       mileage,
            "Výkon (kW)":        power,
            "Rok výroby":        year,
            "Tepelné čerpadlo":  "Ano",   # guaranteed by URL filter
            "Kola":              kola,
            "Náhon 4x4":         "",      # filled from detail page
            "Extra":             suffix_rest,
            "Stav":              "",
            "Zdroj":             "Sauto.cz",
            "Odkaz na auto":     href,
        })

    return cars


async def fetch_detail_data(ctx, url, semaphore):
    """Return (nahon_4x4, power_kw, battery_str, range_str) from a detail page.

    Uses the same browser context so that CMP consent cookies are shared.
    """
    try:
        async with semaphore:
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)
                html = await page.content()
            finally:
                await page.close()
    except Exception:
        return "Ne", "", "", ""

    soup = BeautifulSoup(html, "html.parser")

    pohon = ""
    power_kw = ""
    battery = ""
    dojezd = ""

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            th = row.find("th")
            td = row.find("td")
            if not th or not td:
                continue
            key = th.get_text(strip=True).rstrip(":")
            val = td.get_text(strip=True)
            if key == "Pohon":
                pohon = val
            elif key == "Výkon":
                m = re.search(r'(\d+)\s*kW', val)
                if m:
                    power_kw = m.group(1)
            elif key == "Kapacita akumulátoru":
                m = re.search(r'(\d+(?:[,.]\d+)?)\s*kWh', val)
                if m and float(m.group(1).replace(",", ".")) > 0:
                    battery = m.group(1).replace(",", ".") + " kWh"
            elif key == "Dojezd":
                m = re.search(r'(\d+)\s*km', val)
                if m and int(m.group(1)) > 0:
                    dojezd = m.group(1) + " km"

    awd = (
        "Ano"
        if re.search(
            r'všech\s+kol|4x4|AWD|4MATIC|quattro|xDrive|e-tron\s+4|R4',
            pohon, re.IGNORECASE,
        )
        else "Ne"
    )

    return awd, power_kw, battery, dojezd


async def scrape_sauto():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()

        all_cars = []
        seen_links: set = set()
        page_num = 1

        while True:
            url = BASE_URL if page_num == 1 else f"{BASE_URL}&strana={page_num}"
            print(f"Zpracovávám stránku {page_num}: {url[:80]}")

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)

            if page_num == 1:
                await accept_consent(page)
                await page.wait_for_timeout(3000)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            cars = parse_listing_items(soup)
            new_cars = [c for c in cars if c["Odkaz na auto"] not in seen_links]
            for c in new_cars:
                seen_links.add(c["Odkaz na auto"])
            all_cars.extend(new_cars)

            # Stop if no new results or no "next page" button
            next_btn = soup.find(class_=lambda c: c and "c-paging__btn-next" in c)
            if not next_btn or not new_cars:
                break

            page_num += 1

        await page.close()

        print(f"  Nalezeno celkem {len(all_cars)} inzerátů. Načítám detailní stránky...")

        semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
        detail_results = await asyncio.gather(
            *[fetch_detail_data(ctx, car["Odkaz na auto"], semaphore) for car in all_cars]
        )

        for car, (awd, power_kw, battery, dojezd) in zip(all_cars, detail_results):
            car["Náhon 4x4"] = awd

            # Fall back to detail-page power if listing card had none
            if not car["Výkon (kW)"] and power_kw:
                car["Výkon (kW)"] = power_kw

            # Prepend technical extras (range, battery) before the suffix text
            extra_parts = []
            if dojezd:
                extra_parts.append(f"Dojezd {dojezd}")
            if battery:
                extra_parts.append(f"Baterie {battery}")
            if car["Extra"]:
                extra_parts.append(car["Extra"])
            car["Extra"] = " / ".join(extra_parts)

        df = pd.DataFrame(all_cars, columns=COLS)
        df.drop_duplicates(subset="Odkaz na auto", inplace=True)
        df.to_csv("sauto.csv", index=False, encoding="utf-8")
        print(f"Hotovo – uloženo {len(df)} aut do sauto.csv")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(scrape_sauto())
