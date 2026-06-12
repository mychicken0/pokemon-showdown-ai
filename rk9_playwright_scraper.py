#!/usr/bin/env python3
"""
RK9 Playwright Fallback Scraper

Only uses browser automation for RK9 URLs that failed HTTP parsing.
Cache-first, single browser context, polite delays, resume support.
"""

import asyncio
import json
import hashlib
import time
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# HTML cache directories
HTTP_CACHE_DIR = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/cache")
RENDERED_CACHE_DIR = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/cache_rendered")
RENDERED_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Delay between requests (seconds)
MIN_DELAY = 2.0
MAX_DELAY = 5.0

@dataclass
class FetchResult:
    url: str
    success: bool
    html: Optional[str] = None
    error: Optional[str] = None
    from_rendered_cache: bool = False
    from_http_cache: bool = False

class RK9PlaywrightScraper:
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.last_request_time = 0.0

    async def _get_browser(self) -> Browser:
        """Initialize browser if not already done."""
        if self.browser is None:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (compatible; VGC2026Scraper/1.0)"
            )
        return self.browser

    async def close(self):
        """Close browser and context."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()

    def _cache_paths(self, url: str) -> tuple:
        """Get cache file paths for a URL."""
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        http_cache = HTTP_CACHE_DIR / f"{url_hash}.html"
        http_meta = HTTP_CACHE_DIR / f"{url_hash}.meta.json"
        rendered_cache = RENDERED_CACHE_DIR / f"{url_hash}.html"
        rendered_meta = RENDERED_CACHE_DIR / f"{url_hash}.meta.json"
        return http_cache, http_meta, rendered_cache, rendered_meta

    def _is_cached(self, url: str) -> bool:
        """Check if URL is cached in rendered cache."""
        _, _, rendered_cache, rendered_meta = self._cache_paths(url)
        return rendered_cache.exists() and rendered_meta.exists()

    def _load_rendered_cache(self, url: str) -> Optional[str]:
        """Load HTML from rendered cache."""
        _, _, rendered_cache, _ = self._cache_paths(url)
        if rendered_cache.exists():
            return rendered_cache.read_text(encoding='utf-8')
        return None

    def _save_rendered_cache(self, url: str, html: str, meta: dict):
        """Save HTML to rendered cache with metadata."""
        _, _, rendered_cache, rendered_meta = self._cache_paths(url)
        rendered_cache.write_text(html, encoding='utf-8')
        meta["cached_at"] = time.time()
        meta["url"] = url
        rendered_meta.write_text(json.dumps(meta, indent=2))

    def _respect_rate_limit(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < MIN_DELAY:
            time.sleep(MIN_DELAY - elapsed)

    async def fetch(self, url: str, use_cache: bool = True) -> FetchResult:
        """Fetch a URL, trying HTTP cache first, then rendered cache, then browser."""

        # Check rendered cache first
        if use_cache and self._is_cached(url):
            html = self._load_rendered_cache(url)
            if html:
                return FetchResult(
                    url=url,
                    success=True,
                    html=html,
                    from_rendered_cache=True
                )

        # Check HTTP cache
        http_cache, http_meta, _, _ = self._cache_paths(url)
        if http_cache.exists():
            html = http_cache.read_text(encoding='utf-8')
            # Check if HTTP cache has the team data (has .teamlist or "Team list for:")
            if '.teamlist' in html or 'Team list for:' in html or 'pkmn' in html:
                # Save to rendered cache too
                self._save_rendered_cache(url, html, {"source": "http_cache"})
                return FetchResult(
                    url=url,
                    success=True,
                    html=html,
                    from_http_cache=True
                )

        # Need to use browser
        self._respect_rate_limit()

        try:
            await self._get_browser()
            page = await self.context.new_page()

            # Navigate with timeout
            await page.goto(url, wait_until="networkidle", timeout=60000)

            # Wait for content to render
            await page.wait_for_timeout(3000)

            # Get rendered HTML
            html = await page.content()

            await page.close()

            self.last_request_time = time.time()

            if html and ('.teamlist' in html or 'Team list for:' in html):
                self._save_rendered_cache(url, html, {"source": "playwright"})
                return FetchResult(
                    url=url,
                    success=True,
                    html=html
                )
            else:
                return FetchResult(
                    url=url,
                    success=False,
                    error="Page loaded but no team data found",
                    html=html
                )

        except Exception as e:
            return FetchResult(
                url=url,
                success=False,
                error=str(e)
            )

async def main():
    """Test the scraper with a few RK9 URLs."""
    # Load source index to get RK9 URLs
    with open("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/source_index.json") as f:
        source_index = json.load(f)

    # Get RK9 URLs that are in source_index
    rk9_entries = [e for e in source_index if e.get("source_platform") == "rk9" and e.get("source_url")]

    print(f"Found {len(rk9_entries)} RK9 entries with URLs")

    scraper = RK9PlaywrightScraper()

    try:
        for i, entry in enumerate(rk9_entries[:5]):  # Test first 5
            rank = entry.get("rank")
            url = entry.get("source_url")
            print(f"\n[{i+1}/{min(5, len(rk9_entries))}] Rank {rank}: {url}")

            result = await scraper.fetch(url)

            if result.success:
                source = []
                if result.from_rendered_cache:
                    source.append("rendered_cache")
                if result.from_http_cache:
                    source.append("http_cache")
                src_str = f" ({', '.join(source)})" if source else " (browser)"
                print(f"  ✓ Success{src_str} - {len(result.html)} chars")
                # Save debug file
                debug_path = RENDERED_CACHE_DIR / f"debug_rank_{rank}.html"
                debug_path.write_text(result.html, encoding='utf-8')
            else:
                print(f"  ✗ Failed: {result.error}")

        print(f"\nDone. Rendered cache: {RENDERED_CACHE_DIR}")
    finally:
        await scraper.close()

if __name__ == "__main__":
    import json
    asyncio.run(main())