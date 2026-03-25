import aiohttp
import asyncio
from app.logger import get_logger

DATA_API_URL = "https://data-api.polymarket.com"
logger = get_logger()


async def fetch_open_interest_batch(condition_ids):
    """
    Fetches Open Interest for multiple condition_ids in a single session.
    Returns a dict {condition_id: oi_value}
    """
    if not condition_ids:
        return {}

    results = {}
    url = f"{DATA_API_URL}/oi"

    # Polymarket Data API /oi accepts a single 'market' param or multiple
    # Based on search, we might need to call it per ID or see if it accepts comma-sep
    # Let's try comma-separated first, if not, we gather.

    async with aiohttp.ClientSession() as session:
        # To be safe and efficient, we'll fetch them in parallel
        async def fetch_one(cid):
            try:
                async with session.get(url, params={"market": cid}, timeout=5) as res:
                    if res.status == 200:
                        data = await res.json()
                        if isinstance(data, list) and len(data) > 0:
                            return cid, float(data[0].get("value", 0))
                    logger.debug(
                        f"open_interest non-200 status={res.status} market={cid}"
                    )
            except Exception as e:
                logger.debug(f"open_interest fetch failed market={cid}: {e}")
            return cid, 0.0

        tasks = [fetch_one(cid) for cid in condition_ids]
        completed = await asyncio.gather(*tasks)
        for cid, val in completed:
            results[cid] = val

    return results
