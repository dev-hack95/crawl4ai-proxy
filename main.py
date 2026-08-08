import os
import sys
import asyncio
import logging
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

load_dotenv()


logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("main")

CRAWL4AI_URL = os.environ.get("CRAWL4AI_URL", "http://127.0.0.1:11235/md")
PROXY_API_KEY = os.environ.get("PROXY_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost:5432/crawldb")
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", 86400))  # 24h default
CONTENT_TYPE = "markdown"

pool: Optional[AsyncConnectionPool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=False)
    await pool.open()
    logger.info("DB pool opened")
    try:
        yield
    finally:
        await pool.close()
        logger.info("DB pool closed")


app = FastAPI(lifespan=lifespan)


class LoaderRequest(BaseModel):
    urls: List[str]


def hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


async def get_cached(url: str) -> Optional[str]:
    """Return cached markdown for url if present and within TTL, else None."""
    url_hash = hash_url(url)
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT data, crawl_timestamp
                FROM crawler_data
                WHERE url_hash = %s AND content_type = %s
                """,
                (url_hash, CONTENT_TYPE),
            )
            row = await cur.fetchone()
            if row is None:
                return None

            age = (datetime.now(timezone.utc) - row["crawl_timestamp"]).total_seconds()
            if age > CACHE_TTL_SECONDS:
                logger.info(f"Cache stale for {url} (age {age:.0f}s > {CACHE_TTL_SECONDS}s)")
                return None

            await cur.execute(
                """
                UPDATE crawler_data SET last_accessed = now() WHERE url_hash = %s AND content_type = %s
                """,
                (url_hash, CONTENT_TYPE),
            )
            await conn.commit()
            return row["data"]


async def upsert_cache(url: str, content: str) -> None:
    url_hash = hash_url(url)
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO crawler_data (url, url_hash, content_type, data, crawl_timestamp, last_updated, last_accessed, created_at)
                VALUES (%s, %s, %s, %s, now(), now(), now(), now()) ON CONFLICT (url_hash) DO UPDATE SET data = EXCLUDED.data, crawl_timestamp = now(), last_updated = now(), last_accessed = now()
                """,
                (url, url_hash, CONTENT_TYPE, content),
            )
            await conn.commit()


async def fetch_url(url: str, client: httpx.AsyncClient) -> dict:
    try:
        cached = await get_cached(url)
        if cached is not None:
            logger.info(f"Cache hit for {url}: {len(cached)} chars")
            return {
                "page_content": cached,
                "metadata": {"source": url, "cached": True},
            }

        # Try filter=fit first (strips nav, ads, sign-in prompts)
        resp = await client.post(
            CRAWL4AI_URL,
            json={"url": url, "filter": "fit"},
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("markdown", "")

        # Fallback: if filter=fit stripped too much, retry without filter
        if len(content) < 100:
            logger.info(f"Fallback: {url} returned only {len(content)} chars with filter=fit, retrying raw")
            resp = await client.post(
                CRAWL4AI_URL,
                json={"url": url},
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("markdown", "")
            logger.info(f"Fallback fetched {url}: {len(content)} chars")
        else:
            logger.info(f"Fetched {url}: {len(content)} chars")

        if content and not content.startswith("Error"):
            await upsert_cache(url, content)

        return {
            "page_content": content,
            "metadata": {"source": url, "cached": False},
        }
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return {
            "page_content": f"Error fetching {url}: {str(e)}",
            "metadata": {"source": url},
        }


@app.post("/search")
async def search(req: LoaderRequest, authorization: str = Header(None)):
    if PROXY_API_KEY:
        expected = f"Bearer {PROXY_API_KEY}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Invalid API key")

    logger.info(f"Received {len(req.urls)} URLs to fetch")
    async with httpx.AsyncClient(timeout=60) as client:
        tasks = [fetch_url(url, client) for url in req.urls]
        results = await asyncio.gather(*tasks)
    success = sum(1 for r in results if not r["page_content"].startswith("Error"))
    logger.info(f"Done: {success}/{len(req.urls)} successful")
    return list(results)


@app.get("/health")
async def health():
    return {"status": "ok"}