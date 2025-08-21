import sqlite3
import os
import time
from typing import Optional, Tuple, List

DB_PATH = os.path.join(os.getcwd(), "prices.db")

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    marketplace TEXT NOT NULL,
    sku TEXT,
    url TEXT,
    UNIQUE(marketplace, sku, url)
);
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    price INTEGER,
    in_stock INTEGER,
    ts INTEGER NOT NULL,
    meta TEXT,
    FOREIGN KEY(product_id) REFERENCES products(id)
);
"""

def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def upsert_product(conn: sqlite3.Connection, marketplace: str, sku: Optional[str], url: Optional[str]) -> int:
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO products(marketplace, sku, url) VALUES (?,?,?)", (marketplace, sku, url))
    conn.commit()
    cur.execute("SELECT id FROM products WHERE marketplace=? AND IFNULL(sku,'')=IFNULL(?,'') AND IFNULL(url,'')=IFNULL(?,'')",
                (marketplace, sku, url))
    row = cur.fetchone()
    return row[0]

def insert_price(conn: sqlite3.Connection, product_id: int, price: Optional[int], in_stock: Optional[bool], meta: str="") -> int:
    cur = conn.cursor()
    cur.execute("INSERT INTO price_history(product_id, price, in_stock, ts, meta) VALUES (?,?,?,?,?)",
                (product_id, price, 1 if in_stock else 0, int(time.time()), meta))
    conn.commit()
    return cur.lastrowid

def get_last_prices(conn: sqlite3.Connection, limit: int=50) -> List[Tuple]:
    cur = conn.cursor()
    cur.execute("""
    SELECT p.marketplace, p.sku, p.url, h.price, h.in_stock, h.ts
    FROM price_history h
    JOIN products p ON p.id = h.product_id
    ORDER BY h.ts DESC
    LIMIT ?
    """, (limit,))
    return cur.fetchall()

def get_last_for_product(conn: sqlite3.Connection, marketplace: str, sku: Optional[str], url: Optional[str]) -> List[Tuple]:
    cur = conn.cursor()
    cur.execute("""
    SELECT h.price, h.in_stock, h.ts
    FROM price_history h
    JOIN products p ON p.id = h.product_id
    WHERE p.marketplace=? AND IFNULL(p.sku,'')=IFNULL(?,'') AND IFNULL(p.url,'')=IFNULL(?,'')
    ORDER BY h.ts DESC
    LIMIT 50
    """, (marketplace, sku, url))
    return cur.fetchall()
