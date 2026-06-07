"""Generic aiohttp helpers for JSON-API sources (sauto; later mobile.de).

Sessions are supplied by the caller (an ``aiohttp.ClientSession``); these helpers
only orchestrate paging and concurrency, so ``aiohttp`` itself is not imported here.
"""
import asyncio

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


async def fetch_all_items(session, search_url, params, page_size=100):
    """Page through a search API that returns {pagination:{total}, results:[...]}."""
    items, offset, total = [], 0, None
    while True:
        page_params = {**params, "limit": page_size, "offset": offset}
        async with session.get(search_url, params=page_params) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if total is None:
            total = data["pagination"]["total"]
            print(f"  Celkem {total} inzerátů")
        batch = data["results"]
        items.extend(batch)
        offset += page_size
        if offset >= total or not batch:
            break
    return items


async def fetch_detail(session, url, semaphore):
    """Return the 'result' dict from an item detail endpoint, or {} on error."""
    try:
        async with semaphore:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                return data.get("result", {})
    except Exception:
        return {}


async def fetch_all_details(session, urls, concurrency=20):
    """Fetch many detail URLs concurrently, capped by a semaphore. Order preserved."""
    sem = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*[fetch_detail(session, u, sem) for u in urls])
