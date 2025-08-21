from typing import Optional, Dict, Any
import json, re, aiohttp
from bs4 import BeautifulSoup
from utils import fetch, get_default_headers
from browser import browser_fallback_enabled, get_rendered_html

WB_ENDPOINTS = [
    "https://card.wb.ru/cards/detail?curr=rub&dest={dest}&spp=0&nm={nm}",
    "https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest={dest}&nm={nm}",
]
WB_DESTS = ["-1257786", "123585515", "1257786", "117673"]

def _vol(nm: int) -> int: return int(nm // 100000)
def _part(nm: int) -> int: return int(nm // 1000)

def _basket_urls(nm: int):
    servers = [f"basket-{str(i).zfill(2)}.wb.ru" for i in range(1, 16)]
    servers += [f"static-basket-{str(i).zfill(2)}.wbbasket.ru" for i in range(1, 16)]
    v = _vol(nm); p = _part(nm)
    for host in servers:
        yield f"https://{host}/vol{v}/part{p}/{nm}/info/ru/card.json"

async def _try_cards_api(session: aiohttp.ClientSession, nm: str) -> Optional[Dict[str, Any]]:
    for tmpl in WB_ENDPOINTS:
        for dest in WB_DESTS:
            url = tmpl.format(dest=dest, nm=nm)
            raw = await fetch(session, url, headers=get_default_headers(), tries=2)
            if not raw:
                continue
            try:
                data = json.loads(raw.decode("utf-8", "ignore"))
                products = (data.get("data") or {}).get("products") or []
                if products:
                    p = products[0]
                    price = None
                    if "salePriceU" in p:
                        price = int(p["salePriceU"] // 100)
                    elif "priceU" in p:
                        price = int(p["priceU"] // 100)
                    in_stock = bool(p.get("stocks"))
                    return {"price": price, "in_stock": in_stock, "name": p.get("name")}
            except Exception:
                continue
    return None

async def _try_basket(session: aiohttp.ClientSession, nm: str) -> Optional[Dict[str, Any]]:
    try:
        nm_int = int(nm)
    except Exception:
        return None
    for url in _basket_urls(nm_int):
        raw = await fetch(session, url, headers=get_default_headers(), tries=2)
        if not raw:
            continue
        try:
            data = json.loads(raw.decode("utf-8", "ignore"))
            price = None
            for key in ("salePriceU","priceU","basicPriceU","clientSale"):
                if isinstance(data.get(key), (int, float)):
                    v = data[key]
                    price = int(v // 100) if v > 1000 else int(v)
                    break
            in_stock = True
            name = data.get("imt_name") if isinstance(data, dict) else None
            return {"price": price, "in_stock": in_stock, "name": name}
        except Exception:
            continue
    return None

async def _try_html(session: aiohttp.ClientSession, nm: str) -> Optional[Dict[str, Any]]:
    # Браузерный фоллбек: открыть карточку и достать цену из HTML
    if not browser_fallback_enabled():
        return None
    url = f"https://www.wildberries.ru/catalog/{nm}/detail.aspx"
    html = await get_rendered_html(url, warmup_url="https://www.wildberries.ru/")
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    # Частые селекторы цен WB
    text = ""
    cand = soup.select_one("[data-meta-price], span.price-block__final-price, span.price-block__price")
    if cand:
        text = cand.get_text(strip=True)
    # Парсим число
    import re
    m = re.search(r"(\d[\d\s]+)", text)
    price = int(m.group(1).replace(" ", "")) if m else None
    in_stock = "Нет в наличии" not in html
    return {"price": price, "in_stock": in_stock, "name": soup.title.get_text(strip=True) if soup.title else None}

async def resolve_and_fetch(session: aiohttp.ClientSession, sku: Optional[str]=None, url: Optional[str]=None):
    nm = None
    if sku: nm = sku
    elif url:
        m = re.search(r"/catalog/(\d+)/", url)
        if m:
            nm = m.group(1)
    if not nm:
        return None

    data = await _try_cards_api(session, nm)
    if data:
        return data
    data = await _try_basket(session, nm)
    if data:
        return data
    return await _try_html(session, nm)
