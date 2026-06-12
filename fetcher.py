#!/usr/bin/env python3
"""
Phase T2 - Fetcher with Caching
HTTP/API-first fetching with caching, retry logic, and browser fallback.
"""

import json
import time
import hashlib
from pathlib import Path
from typing import Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class TeamFetcher:
    def __init__(self, cache_dir: Path, delay_range: Tuple[float, float] = (1.5, 3.0)):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay_range = delay_range

        # Session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; VGC2026Scraper/1.0; +https://github.com)"
        })

        self.last_request_time = 0

    def _cache_path(self, url: str) -> Path:
        """Generate cache file path from URL."""
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        return self.cache_dir / f"{url_hash}.html"

    def _cache_meta_path(self, url: str) -> Path:
        """Generate cache metadata file path."""
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        return self.cache_dir / f"{url_hash}.meta.json"

    def _is_cached(self, url: str) -> bool:
        """Check if URL is cached."""
        cache_file = self._cache_path(url)
        meta_file = self._cache_meta_path(url)
        return cache_file.exists() and meta_file.exists()

    def _load_cached(self, url: str) -> Optional[str]:
        """Load cached content."""
        cache_file = self._cache_path(url)
        if cache_file.exists():
            return cache_file.read_text(encoding='utf-8')
        return None

    def _save_cache(self, url: str, content: str, meta: dict):
        """Save content to cache with metadata."""
        cache_file = self._cache_path(url)
        meta_file = self._cache_meta_path(url)

        cache_file.write_text(content, encoding='utf-8')
        meta["fetched_at"] = time.time()
        meta["url"] = url
        meta_file.write_text(json.dumps(meta, indent=2))

    def _respect_rate_limit(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self.last_request_time
        min_delay = self.delay_range[0]
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)

    def fetch(self, url: str, use_cache: bool = True) -> Tuple[Optional[str], dict]:
        """
        Fetch URL with caching.
        Returns: (content, meta_dict)
        meta_dict contains: success, from_cache, error, status_code, etc.
        """
        meta = {
            "url": url,
            "success": False,
            "from_cache": False,
            "error": None,
            "status_code": None,
            "content_length": 0,
        }

        # Check cache first
        if use_cache and self._is_cached(url):
            content = self._load_cached(url)
            if content:
                meta["success"] = True
                meta["from_cache"] = True
                meta["content_length"] = len(content)
                return content, meta

        # Respect rate limit
        self._respect_rate_limit()

        # Fetch
        try:
            self.last_request_time = time.time()
            resp = self.session.get(url, timeout=30)
            meta["status_code"] = resp.status_code

            if resp.status_code == 200:
                content = resp.text
                meta["success"] = True
                meta["content_length"] = len(content)

                if use_cache:
                    self._save_cache(url, content, meta.copy())

                return content, meta
            else:
                meta["error"] = f"HTTP {resp.status_code}"
                return None, meta

        except requests.RequestException as e:
            meta["error"] = str(e)
            return None, meta


def main():
    """Test fetcher with a few URLs."""
    cache_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/cache")
    fetcher = TeamFetcher(cache_dir, delay_range=(1.5, 2.0))

    # Test with a known working URL
    test_url = "https://play.limitlesstcg.com/tournament/69cd69a336f5b5c303dc45bb/player/tingusthepingus/teamlist"

    print(f"Fetching {test_url}...")
    content, meta = fetcher.fetch(test_url, use_cache=True)

    print(f"Success: {meta['success']}")
    print(f"From cache: {meta['from_cache']}")
    print(f"Status: {meta['status_code']}")
    print(f"Length: {meta['content_length']}")
    if meta['error']:
        print(f"Error: {meta['error']}")

if __name__ == "__main__":
    main()