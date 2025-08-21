from typing import Optional, Dict, Any
import re, asyncio
from bs4 import BeautifulSoup
from utils import fetch, get_default_headers
from browser import browser_fallback_enabled, get_rendered_html
import aiohttp

PRICE_KEYS = ["price", "final_price", "priceValue", "cellTrackingPrice", "discountedPrice"]

def _extract_json_candidates(html: str):
    soup = BeautifulSoup(html, "lxml")
    for node in soup.select("script[type='application/ld+json']"):
        if node.string:
            yield node.string
    for node in soup.find_all("script"):
        txt = node.string or ""
        if txt and ('"price"' in txt or "priceValue" in txt or "ozon" in txt.lower() or "nuxt" in txt.lower()):
            yield txt

def _find_price_in_blob(blob: str) -> Optional[int]:
    for key in PRICE_KEYS:
        m = re.search(fr'"{key}"\s*:\s*"?(\d+)[\.,]?\d*"?', blob)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                continue
    m2 = re.search(r'(?:price|priceValue)"?\s*:\s*"?(?:RUB|₽)?\s*(\d+)"?', blob)
    if m2:
        try:
            return int(m2.group(1))
        except Exception:
            return None
    return None

async def _try_requests(session: aiohttp.ClientSession, url: str) -> Optional[Dict[str, Any]]:
    # Чистим URL от трекинга
    try:
        from urllib.parse import urlparse, urlunparse
        pr = urlparse(url)
        url = urlunparse(pr._replace(query="", fragment=""))
    except Exception:
        pass
    headers = get_default_headers()
    # Прогрев сессии для куки
    try:
        async with session.get("https://www.ozon.ru/", headers=headers) as r:
            await r.text()
    except Exception:
        pass
    await asyncio.sleep(0.3)
    headers.update({"referer": "https://www.ozon.ru/", "origin": "https://www.ozon.ru"})
    try:
        async with session.get(url, headers=headers, allow_redirects=True) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()
    except Exception:
        return None
    # Разбор
    price = None
    for blob in _extract_json_candidates(html):
        p = _find_price_in_blob(blob)
        if p:
            price = p
            break
    in_stock = "Нет в наличии" not in html and "товара нет" not in html.lower()
    return {"price": price, "in_stock": in_stock, "name": None}

async def _try_browser(url: str) -> Optional[Dict[str, Any]]:
    if not browser_fallback_enabled():
        return None
    html = await get_rendered_html(url, warmup_url="https://www.ozon.ru/", referer="https://www.ozon.ru/")
    if not html:
        return None
    price = None
    for blob in _extract_json_candidates(html):
        p = _find_price_in_blob(blob)
        if p:
            price = p
            break
    in_stock = "Нет в наличии" not in html and "товара нет" not in html.lower()
    soup = BeautifulSoup(html, "lxml")
    name = soup.title.get_text(strip=True) if soup.title else None
    return {"price": price, "in_stock": in_stock, "name": name}

async def resolve_and_fetch(session: aiohttp.ClientSession, sku: Optional[str]=None, url: Optional[str]=None) -> Optional[Dict[str, Any]]:
    if not url:
        return None
    data = await _try_requests(session, url)
    if data and (data["price"] is not None or data["in_stock"] is not None):
        return data
    return await _try_browser(url)
