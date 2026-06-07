from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import time
from typing import Any

import httpx

from .utils.time import utc_now_iso

SECRET_PARAM_NAMES = {"apikey", "api_key", "token", "access_token", "key"}


class CacheFetchError(RuntimeError):
    pass


class FileCache:
    def __init__(self, base_dir: Path, ttl_seconds: int = 6 * 60 * 60) -> None:
        self.base_dir = base_dir
        self.ttl_seconds = ttl_seconds
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_json(
        self,
        source_name: str,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        cached = self._read_cached(source_name, url, params)
        if cached is not None:
            return cached

        try:
            with httpx.Client(timeout=12.0, follow_redirects=True) as client:
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:300].replace("\n", " ")
            raise CacheFetchError(
                f"{source_name} HTTP {exc.response.status_code} while requesting {url}: {body}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise CacheFetchError(f"{source_name} request failed for {url}: {exc}") from exc

        self._write_cached(source_name, url, params, data)
        return data

    def get_text(
        self,
        source_name: str,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        cached = self._read_cached(source_name, url, params)
        if cached is not None:
            return str(cached)

        try:
            with httpx.Client(timeout=12.0, follow_redirects=True) as client:
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.text
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:300].replace("\n", " ")
            raise CacheFetchError(
                f"{source_name} HTTP {exc.response.status_code} while requesting {url}: {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise CacheFetchError(f"{source_name} request failed for {url}: {exc}") from exc

        self._write_cached(source_name, url, params, data)
        return data

    def resolve_final_url(
        self,
        source_name: str,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> str | None:
        cached = self._read_cached(f"{source_name} final_url", url, None)
        if cached is not None:
            return str(cached)

        try:
            with httpx.Client(timeout=3.0, follow_redirects=True) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()
                final_url = str(response.url)
        except httpx.HTTPError:
            return None

        self._write_cached(f"{source_name} final_url", url, None, final_url)
        return final_url

    def _read_cached(
        self, source_name: str, url: str, params: dict[str, Any] | None
    ) -> Any | None:
        path = self._path_for(source_name, url, params)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        fetched_epoch = payload.get("fetched_epoch")
        if self.ttl_seconds > 0 and fetched_epoch and time() - float(fetched_epoch) > self.ttl_seconds:
            return None
        return payload.get("data")

    def _write_cached(
        self, source_name: str, url: str, params: dict[str, Any] | None, data: Any
    ) -> None:
        path = self._path_for(source_name, url, params)
        payload = {
            "source_name": source_name,
            "url": url,
            "params": self._redact_params(params or {}),
            "fetched_at": utc_now_iso(),
            "fetched_epoch": time(),
            "data": data,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _path_for(self, source_name: str, url: str, params: dict[str, Any] | None) -> Path:
        raw = json.dumps(
            {"source_name": source_name, "url": url, "params": params or {}},
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        safe_source = "".join(ch if ch.isalnum() else "_" for ch in source_name.lower()).strip("_")
        return self.base_dir / f"{safe_source}_{digest}.json"

    @staticmethod
    def _redact_params(params: dict[str, Any]) -> dict[str, Any]:
        redacted: dict[str, Any] = {}
        for key, value in params.items():
            redacted[key] = "***REDACTED***" if key.lower() in SECRET_PARAM_NAMES else value
        return redacted
