import asyncio
import os
import logging
import ssl
from typing import Optional, Dict
import aiohttp
import certifi

logger = logging.getLogger(__name__)

def jitter(base: float, spread: float = 0.3) -> float:
    lo = base * (1 - spread)
    hi = base * (1 + spread)
    import random
    return random.uniform(lo, hi)

def get_default_headers() -> Dict[str, str]:
    ua = os.getenv("USER_AGENT", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    return {
        "user-agent": ua,
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.7,en;q=0.6",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "upgrade-insecure-requests": "1",
        "sec-fetch-site": "none",
        "sec-fetch-mode": "navigate",
        "sec-fetch-user": "?1",
        "sec-fetch-dest": "document",
    }

def get_ssl_context():
    """SSL контекст с корнями из certifi. Если SSL_VERIFY=false — отключить проверку (не для прод)."""
    verify = os.getenv("SSL_VERIFY", "true").lower() != "false"
    if not verify:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    cafile = certifi.where()
    return ssl.create_default_context(cafile=cafile)

async def fetch(session: aiohttp.ClientSession, url: str, **kwargs) -> Optional[bytes]:
    tries = kwargs.pop("tries", 3)
    backoff = kwargs.pop("backoff", 1.6)
    for attempt in range(1, tries + 1):
        try:
            async with session.get(url, **kwargs) as resp:
                if resp.status == 200:
                    return await resp.read()
                elif resp.status in (403, 429):
                    wt = jitter(backoff * attempt, 0.5)
                    logger.warning("Got %s for %s, retrying in %.1fs...", resp.status, url, wt)
                    await asyncio.sleep(wt)
                else:
                    logger.error("HTTP %s for %s", resp.status, url)
                    return None
        except Exception as e:
            wt = jitter(backoff * attempt, 0.5)
            logger.warning("Error %s for %s, retrying in %.1fs...", e, url, wt)
            await asyncio.sleep(wt)
    return None
