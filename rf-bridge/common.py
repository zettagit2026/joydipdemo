"""Small shared utilities: config loading + JWT login to CEMA backend."""
from __future__ import annotations

import os
import time
import logging
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

CFG_DIR = Path(__file__).parent
load_dotenv(CFG_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


def cfg(key: str, default: Optional[str] = None) -> str:
    v = os.environ.get(key, default)
    if v is None:
        raise RuntimeError(f"Missing config: {key}")
    return v


def cfg_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        return default


def cfg_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except ValueError:
        return default


class CemaClient:
    """Thin REST client that keeps a JWT and auto-refreshes on 401."""

    def __init__(self) -> None:
        self.base = cfg("CEMA_API_URL").rstrip("/")
        self.email = cfg("CEMA_EMAIL")
        self.password = cfg("CEMA_PASSWORD")
        self.token: Optional[str] = None
        self.log = logging.getLogger("cema-client")

    def login(self) -> str:
        r = requests.post(
            f"{self.base}/api/auth/login",
            json={"email": self.email, "password": self.password},
            timeout=10,
        )
        r.raise_for_status()
        self.token = r.json()["token"]
        self.log.info("Authenticated as %s", self.email)
        return self.token

    def ensure_token(self) -> str:
        if not self.token:
            return self.login()
        return self.token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.ensure_token()}"}

    def post(self, path: str, json: dict, retries: int = 1) -> dict:
        for attempt in range(retries + 1):
            try:
                r = requests.post(f"{self.base}{path}", json=json,
                                  headers=self._headers(), timeout=15)
                if r.status_code == 401 and attempt < retries:
                    self.log.warning("401 — refreshing token and retrying")
                    self.token = None
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                if attempt == retries:
                    raise
                self.log.warning("POST %s failed (%s); retrying", path, e)
                time.sleep(1.0)
        return {}
