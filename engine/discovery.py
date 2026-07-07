"""Token discovery via the free GeckoTerminal API (no key required).

We pull two candidate pools lists for Solana — trending and top-by-volume —
and normalize each into a `TokenSnapshot`. GeckoTerminal already returns
market cap, liquidity, multi-window volume, price change and buy/sell counts,
so a single free source covers the whole scan.

Docs: https://www.geckoterminal.com/dex-api  (rate limit ~30 calls/min free)
"""

from __future__ import annotations

import logging
from typing import Dict, List

import requests

from .models import TokenSnapshot

BASE = "https://api.geckoterminal.com/api/v2"
HEADERS = {"Accept": "application/json;version=20230302"}
NETWORK = "solana"

log = logging.getLogger("radar.discovery")


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _snapshots_from_payload(payload: dict) -> List[TokenSnapshot]:
    """Turn a GeckoTerminal pools payload (data + included) into snapshots."""
    included = payload.get("included", []) or []
    tokens_by_id: Dict[str, dict] = {
        item["id"]: item.get("attributes", {})
        for item in included
        if item.get("type") == "token"
    }
    out: List[TokenSnapshot] = []
    for pool in payload.get("data", []) or []:
        try:
            snap = TokenSnapshot.from_geckoterminal(pool, tokens_by_id)
            if snap.address:
                out.append(snap)
        except Exception as e:  # never let one bad pool kill the scan
            log.warning("skip pool: %s", e)
    return out


def fetch_trending(pages: int = 1) -> List[TokenSnapshot]:
    snaps: List[TokenSnapshot] = []
    for page in range(1, pages + 1):
        payload = _get(
            f"/networks/{NETWORK}/trending_pools",
            params={"page": page, "duration": "1h", "include": "base_token"},
        )
        snaps.extend(_snapshots_from_payload(payload))
    return snaps


def fetch_top_by_volume(pages: int = 1) -> List[TokenSnapshot]:
    snaps: List[TokenSnapshot] = []
    for page in range(1, pages + 1):
        payload = _get(
            f"/networks/{NETWORK}/pools",
            params={"page": page, "sort": "h24_volume_usd_desc",
                    "include": "base_token"},
        )
        snaps.extend(_snapshots_from_payload(payload))
    return snaps


def _fetch_pool(address: str) -> TokenSnapshot | None:
    """Treat `address` as a pool/pair address and fetch that single pool."""
    payload = _get(
        f"/networks/{NETWORK}/pools/{address}",
        params={"include": "base_token"},
    )
    data = payload.get("data")
    if isinstance(data, dict):  # single-pool endpoint returns an object
        payload = {"data": [data], "included": payload.get("included", [])}
    snaps = _snapshots_from_payload(payload)
    return snaps[0] if snaps else None


def fetch_token(address: str) -> TokenSnapshot | None:
    """Refresh a single token, given either its mint or a pool/pair address.

    Tries the token-mint endpoint first (returns the deepest-liquidity pool);
    if that 404s (the caller passed a pool/pair address instead, e.g. copied
    from a chart URL), falls back to the single-pool endpoint. Returns None
    on any hard failure so callers can skip gracefully.
    """
    try:
        payload = _get(
            f"/networks/{NETWORK}/tokens/{address}/pools",
            params={"include": "base_token", "sort": "h24_volume_usd_desc"},
        )
        snaps = _snapshots_from_payload(payload)
        if snaps:
            return max(snaps, key=lambda s: s.liquidity)
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 404:
            log.warning("fetch_token(%s) failed: %s", address, e)
            return None
        # 404 -> maybe it's a pool address; fall through to the pool lookup
    except Exception as e:
        log.warning("fetch_token(%s) failed: %s", address, e)
        return None

    try:
        return _fetch_pool(address)
    except Exception as e:
        log.warning("fetch_token(%s) pool fallback failed: %s", address, e)
        return None


def discover(pages: int = 1) -> List[TokenSnapshot]:
    """Combined discovery feed, de-duplicated by token mint address.

    Keeps the snapshot with the deepest liquidity when the same token shows
    up in more than one pool/list.
    """
    seen: Dict[str, TokenSnapshot] = {}
    collected: List[TokenSnapshot] = []
    try:
        collected += fetch_trending(pages)
    except Exception as e:
        log.warning("trending fetch failed: %s", e)
    try:
        collected += fetch_top_by_volume(pages)
    except Exception as e:
        log.warning("top-by-volume fetch failed: %s", e)

    for snap in collected:
        existing = seen.get(snap.address)
        if existing is None or snap.liquidity > existing.liquidity:
            seen[snap.address] = snap
    return list(seen.values())
