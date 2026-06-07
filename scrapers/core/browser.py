"""Generic Playwright helpers for browser-based sources (autodraft, energycars)."""


async def accept_cookies(page, texts):
    """Click the first matching cookie-consent button; ignore if none appears."""
    for t in texts:
        try:
            await page.click(f'text="{t}"', timeout=2000)
            await page.wait_for_timeout(500)
            return
        except Exception:
            pass


async def load_all(page, labels):
    """Click each 'load more' label repeatedly until it disappears."""
    for label in labels:
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
