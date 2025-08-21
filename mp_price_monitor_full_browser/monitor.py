import os, csv, asyncio, time, argparse, logging
from typing import Optional, List
from dotenv import load_dotenv
import aiohttp
from aiohttp import TCPConnector
from pydantic import BaseModel, Field

from storage import init_db, upsert_product, insert_price, get_last_prices, get_last_for_product
from alert import send_telegram
from marketplaces import wb as wb_adapter
from marketplaces import ozon as ozon_adapter
from utils import get_default_headers, jitter, get_ssl_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("monitor")

class Target(BaseModel):
    marketplace: str
    sku: Optional[str] = None
    url: Optional[str] = None
    desired_price: Optional[int] = Field(default=None)
    rise_alert_pct: Optional[float] = Field(default=0.0)
    drop_alert_pct: Optional[float] = Field(default=5.0)
    notes: Optional[str] = ""

ADAPTERS = {
    "wb": wb_adapter.resolve_and_fetch,
    "ozon": ozon_adapter.resolve_and_fetch,
}

async def process_target(session: aiohttp.ClientSession, t: Target, conn, alerts: List[str]):
    adapter = ADAPTERS.get(t.marketplace.lower())
    if not adapter:
        logger.warning("No adapter for %s", t.marketplace)
        return

    data = await adapter(session, sku=t.sku, url=t.url)
    product_id = upsert_product(conn, t.marketplace, t.sku, t.url)

    if not data:
        logger.warning("No data for %s %s %s", t.marketplace, t.sku, t.url)
        insert_price(conn, product_id, None, None, meta="{}")
        return

    price = data.get("price")
    in_stock = data.get("in_stock")
    insert_price(conn, product_id, price, in_stock, meta="{}")
    logger.info("Saved: %s %s %s -> price=%s stock=%s", t.marketplace, t.sku, t.url, price, in_stock)

    # Логика алертов
    last = get_last_for_product(conn, t.marketplace, t.sku, t.url)
    if len(last) >= 2 and last[1][0] is not None:
        prev_price = last[1][0]
        if price is not None and prev_price:
            diff = price - prev_price
            pct = (diff / prev_price) * 100.0
            if t.rise_alert_pct and pct >= t.rise_alert_pct:
                alerts.append(f"⬆️ {t.marketplace} {t.sku or t.url}\nЦена выросла на {pct:.1f}%: {prev_price} → {price} ₽")
            if t.drop_alert_pct and (-pct) >= t.drop_alert_pct:
                alerts.append(f"⬇️ {t.marketplace} {t.sku or t.url}\nЦена упала на {abs(pct):.1f}%: {prev_price} → {price} ₽")
    if t.desired_price and price is not None and price <= t.desired_price:
        alerts.append(f"🎯 {t.marketplace} {t.sku or t.url}\nДостигнута целевая цена {t.desired_price} ₽ (текущая: {price} ₽)")

async def run_once(targets: List[Target]):
    conn = init_db()
    timeout = aiohttp.ClientTimeout(total=int(os.getenv("REQUEST_TIMEOUT", "25")))
    headers = get_default_headers()
    alerts: List[str] = []
    connector = TCPConnector(ssl=get_ssl_context())
    async with aiohttp.ClientSession(timeout=timeout, headers=headers, connector=connector) as session:
        for t in targets:
            await process_target(session, t, conn, alerts)
            await asyncio.sleep(jitter(1.0, 0.7))
    if alerts:
        msg = "🛍 <b>Мониторинг маркетплейсов</b>\n\n" + "\n\n".join(alerts)
        await send_telegram(msg)

def load_targets(path: str = "targets.csv") -> List[Target]:
    out: List[Target] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            desired_price = None
            if row.get("desired_price"):
                try:
                    desired_price = int(float(row["desired_price"]))
                except Exception:
                    desired_price = None
            rise_alert = float(row["rise_alert_pct"]) if row.get("rise_alert_pct") else 0.0
            drop_alert = float(row["drop_alert_pct"]) if row.get("drop_alert_pct") else 5.0
            out.append(Target(
                marketplace=row.get("marketplace","").strip(),
                sku=row.get("sku") or None,
                url=row.get("url") or None,
                desired_price=desired_price,
                rise_alert_pct=rise_alert,
                drop_alert_pct=drop_alert,
                notes=row.get("notes") or "",
            ))
    return out

def report_last(limit: int = 30):
    conn = init_db()
    rows = get_last_prices(conn, limit=limit)
    from datetime import datetime
    print("Время | МП | SKU | Цена | Налич | URL")
    for r in rows:
        mp, sku, url, price, stock, ts = r
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{dt} | {mp:4} | {sku or '-':12} | {str(price) if price is not None else '-':>8} | {'OK' if stock else 'NO':2} | {url or ''}")

def report_product(marketplace: str, sku: Optional[str], url: Optional[str]):
    conn = init_db()
    rows = get_last_for_product(conn, marketplace, sku, url)
    from datetime import datetime
    print("Время | Цена | Налич")
    for price, stock, ts in rows:
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{dt} | {str(price) if price is not None else '-':>8} | {'OK' if stock else 'NO':2}")

def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Монитор цен WB/Ozon")
    ap.add_argument("--run", choices=["once", "loop"], default="once", help="запустить один раз или в цикле")
    ap.add_argument("--every", type=int, default=600, help="интервал циклического запуска в секундах")
    ap.add_argument("--report", choices=["last", "product"], help="режим отчёта")
    ap.add_argument("--limit", type=int, default=30, help="строк в отчёте last")
    ap.add_argument("--sku")
    ap.add_argument("--url")
    ap.add_argument("--marketplace")
    args = ap.parse_args()

    if args.report == "last":
        report_last(limit=args.limit)
        return
    if args.report == "product":
        if not args.marketplace:
            print("--marketplace обязателен (wb|ozon)")
            return
        report_product(args.marketplace, args.sku, args.url)
        return

    targets = load_targets()
    if args.run == "once":
        asyncio.run(run_once(targets))
    else:
        while True:
            asyncio.run(run_once(targets))
            time.sleep(args.every)

if __name__ == "__main__":
    main()
