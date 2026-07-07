"""Persistence for Radar — pluggable KV backend.

State (tracked positions, alerts, admins) must live outside the process so
the bot works on serverless / ephemeral hosts. Two backends share one
interface:

  * JsonStore    — a local JSON file. Zero setup, for dev / a single VM.
  * UpstashStore — Upstash Redis over its REST API (needs only `requests`,
                   so it works from serverless functions and cron jobs).

`get_store()` picks Upstash automatically when its env vars are present,
otherwise falls back to the JSON file. Higher-level position helpers are
built on the small get/set/delete KV surface so both backends just work.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Dict, List, Optional

import requests

from .models import Position

POSITIONS_PREFIX = "positions:"      # positions:<user_id> -> JSON list
POSITION_USERS_KEY = "position_users"  # JSON list of user ids with positions


class KVStore:
    """Minimal key/value surface every backend implements."""

    def get(self, key: str) -> Optional[str]:
        raise NotImplementedError

    def set(self, key: str, value: str) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    # ---- position helpers (shared, built on get/set/delete) -------------

    def _load_list(self, key: str) -> list:
        raw = self.get(key)
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return []

    def _user_key(self, user_id) -> str:
        return f"{POSITIONS_PREFIX}{user_id}"

    def _register_user(self, user_id) -> None:
        users = set(self._load_list(POSITION_USERS_KEY))
        if str(user_id) not in users:
            users.add(str(user_id))
            self.set(POSITION_USERS_KEY, json.dumps(sorted(users)))

    def get_positions(self, user_id) -> List[Position]:
        return [Position.from_dict(d) for d in self._load_list(self._user_key(user_id))]

    def save_positions(self, user_id, positions: List[Position]) -> None:
        if positions:
            self.set(self._user_key(user_id),
                     json.dumps([p.to_dict() for p in positions]))
            self._register_user(user_id)
        else:
            self.delete(self._user_key(user_id))

    def add_position(self, user_id, pos: Position) -> None:
        positions = self.get_positions(user_id)
        # replace an existing position on the same token rather than dup it
        positions = [p for p in positions if p.address != pos.address]
        positions.append(pos)
        self.save_positions(user_id, positions)

    def remove_position(self, user_id, address: str) -> bool:
        positions = self.get_positions(user_id)
        remaining = [p for p in positions if p.address != address]
        self.save_positions(user_id, remaining)
        return len(remaining) < len(positions)

    def all_position_users(self) -> List[str]:
        return [str(u) for u in self._load_list(POSITION_USERS_KEY)]

    def all_positions(self) -> Dict[str, List[Position]]:
        return {u: self.get_positions(u) for u in self.all_position_users()}


class JsonStore(KVStore):
    """File-backed KV. Thread-safe for a single process."""

    def __init__(self, path: str = "radar_state.json"):
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (ValueError, OSError):
            return {}

    def _write(self, data: dict) -> None:
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)  # atomic on same filesystem

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._read().get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            data = self._read()
            data[key] = value
            self._write(data)

    def delete(self, key: str) -> None:
        with self._lock:
            data = self._read()
            if key in data:
                del data[key]
                self._write(data)


class UpstashStore(KVStore):
    """Upstash Redis via its REST API. Serverless/cron friendly.

    Set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN (both shown in
    the Upstash console / Vercel KV integration).
    """

    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    def _cmd(self, *args) -> Optional[str]:
        resp = requests.post(self.url, headers=self.headers,
                             json=list(args), timeout=15)
        resp.raise_for_status()
        return resp.json().get("result")

    def get(self, key: str) -> Optional[str]:
        return self._cmd("GET", key)

    def set(self, key: str, value: str) -> None:
        self._cmd("SET", key, value)

    def delete(self, key: str) -> None:
        self._cmd("DEL", key)


def get_store() -> KVStore:
    """Return Upstash if configured, else a local JSON store."""
    url = os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if url and token:
        return UpstashStore(url, token)
    return JsonStore(os.environ.get("RADAR_STATE_FILE", "radar_state.json"))
