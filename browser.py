import os, asyncio, logging
from typing import Optional
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

def browser_fallback_enabled() -> bool:
    return os.getenv("BROWSER_FALLBACK", "true").lower() == "true"

@asynccontextmanager
async def new_browser_context():
    # Запуск Chromium через Playwright
    from playwright.async_api import async_playwright
    ua = os.getenv("USER_AGENT", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ])
        context = await browser.new_context(locale="ru-RU", user_agent=ua)
        try:
            yield context
        finally:
            await context.close()
            await browser.close()

async def get_rendered_html(url: str, warmup_url: Optional[str] = None, referer: Optional[str] = None, wait_until: str = "networkidle", timeout_ms: int = 20000) -> Optional[str]:
    """Открывает страницу в headless Chromium и возвращает финальный HTML после рендеринга JS."""
    try:
        async with new_browser_context() as ctx:
            if warmup_url:
                page0 = await ctx.new_page()
                await page0.goto(warmup_url, wait_until="domcontentloaded", timeout=timeout_ms)
                await page0.close()
            page = await ctx.new_page()
            if referer:
                page.set_extra_http_headers({"referer": referer})
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            html = await page.content()
            await page.close()
            return html
    except Exception as e:
        logger.warning("Playwright error for %s: %s", url, e)
        return None
