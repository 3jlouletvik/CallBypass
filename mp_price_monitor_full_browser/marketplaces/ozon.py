from typing import Optional, Dict, Any
import re
import asyncio
from bs4 import BeautifulSoup
from utils import get_default_headers
from browser import browser_fallback_enabled, get_rendered_html
import aiohttp


PRICE_KEYS = ['price', 'final_price', 'priceValue', 'cellTrackingPrice', 'discountedPrice']

def _extract_json_candidates(html: str):
    soup = BeautifulSoup(html, "lxml")
    # JSON-LD blobs
    for node in soup.select("script[type='application/ld+json']"):
        if node.string:
            yield node.string
    # Other scripts that might contain state with prices
    for node in soup.find_all("script"):
        txt = node.string or ""
        if not txt:
            continue
        if '"price"' in txt or "priceValue" in txt or "ozon" in txt.lower() or "nuxt" in txt.lower():
            yield txt

def _try_parse_json_price(blob: str):
    import json
    try:
        data = json.loads(blob)
    except Exception:
        return None
    # JSON-LD Product format: {"offers": {"price": "1990"}}
    try:
        # array of JSON-LD
        if isinstance(data, list):
            for item in data:
                p = _try_parse_json_price(json.dumps(item))
                if p:
                    return p
            return None
        offers = data.get("offers") if isinstance(data, dict) else None
        if isinstance(offers, dict):
            price = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
            if isinstance(price, (int, float)):
                return int(price)
            if isinstance(price, str):
                digits = re.sub(r"[^\d]", "", price)
                if digits:
                    return int(digits)
    except Exception:
        pass
    # Walk through dict/list heuristically
    def walk(x):
        import re
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, (int, float)) and any(s in k.lower() for s in ["price", "cost", "value"]):
                    return int(v)
                if isinstance(v, str) and any(s in k.lower() for s in ["price", "cost", "value"]):
                    digits = re.sub(r"[^\d]", "", v)
                    if digits:
                        return int(digits)
                r = walk(v)
                if r:
                    return r
        if isinstance(x, list):
            for it in x:
                r = walk(it)
                if r:
                    return r
        return None
    try:
        return walk(data)
    except Exception:
        return None

def _find_price_in_blob(blob: str):
    p = _try_parse_json_price(blob)
    if p:
        return p
    m = re.search(r'(?i)"price"\s*:\s*"*([\d\s\u00A0]+)', blob)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
        if digits:
            return int(digits)
    m2 = re.search(r'(?i)(?:price|priceValue)"?\s*:\s*"?(?:RUB|₽)?\s*([\d\s\u00A0]+)"?', blob)
    if m2:
        digits = re.sub(r"[^\d]", "", m2.group(1))
        if digits:
            return int(digits)
    return None

def _extract_dom_price(html: str):
    soup = BeautifulSoup(html, "lxml")
    meta = soup.select_one('meta[itemprop="price"]')
    if meta and meta.get("content"):
        digits = re.sub(r"[^\d]", "", meta["content"])
        if digits:
            return int(digits)
    # scan text nodes for ₽
    text_blocks = soup.find_all(text=re.compile(r"\d[\d\s\u00A0]*\s*₽"))
    for t in text_blocks:
        digits = re.sub(r"[^\d]", "", t)
        if digits:
            return int(digits)
    # number near word "цена"
    text_blocks = soup.find_all(text=re.compile(r"(цена|Цена).{0,10}\d[\d\s\u00A0]+"))
    for t in text_blocks:
        digits = re.sub(r"[^\d]", "", t)
        if digits:
            return int(digits)
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
