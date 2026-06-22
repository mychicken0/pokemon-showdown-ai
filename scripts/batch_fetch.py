#!/usr/bin/env python3
"""
Batch fetcher - processes all URLs from source_index.json
"""

import json
import time
from pathlib import Path
from fetcher import TeamFetcher

def main():
    # Load source index
    source_index_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/source_index.json")
    with open(source_index_path) as f:
        source_index = json.load(f)

    # Filter entries with URLs
    entries_with_urls = [e for e in source_index if e.get("source_url")]
    print(f"Total entries with URLs: {len(entries_with_urls)}")

    # Initialize fetcher
    cache_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/cache")
    fetcher = TeamFetcher(cache_dir, delay_range=(1.5, 2.5))

    # Load existing fetch log
    fetch_log_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/vgc2026_top200_fetch_log.csv")
    if fetch_log_path.exists():
        with open(fetch_log_path) as f:
            # Simple check - count lines
            lines = f.readlines()
            print(f"Existing fetch log: {len(lines)-1} entries")
    else:
        # Create header
        with open(fetch_log_path, 'w') as f:
            f.write("rank,player,url,source_platform,success,from_cache,status_code,error,content_length,fetched_at\n")

    success_count = 0
    fail_count = 0
    cache_hits = 0

    for i, entry in enumerate(entries_with_urls):
        rank = entry.get("rank")
        player = entry.get("player")
        url = entry.get("source_url")
        platform = entry.get("source_platform")

        if not url:
            continue

        print(f"[{i+1}/{len(entries_with_urls)}] Rank {rank}: {player} ({platform})")

        content, meta = fetcher.fetch(url, use_cache=True)

        # Log result
        log_entry = {
            "rank": rank,
            "player": player,
            "url": url,
            "source_platform": platform,
            "success": meta["success"],
            "from_cache": meta["from_cache"],
            "status_code": meta.get("status_code"),
            "error": meta.get("error"),
            "content_length": meta.get("content_length"),
            "fetched_at": time.time()
        }

        with open(fetch_log_path, 'a') as f:
            f.write(f"{rank},{player},{url},{platform},{meta['success']},{meta['from_cache']},{meta.get('status_code')},{meta.get('error') or ''},{meta.get('content_length')},{time.time()}\n")

        if meta["success"]:
            success_count += 1
            if meta["from_cache"]:
                cache_hits += 1
            print(f"  ✓ {meta['content_length']} bytes {'(cached)' if meta['from_cache'] else ''}")
        else:
            fail_count += 1
            print(f"  ✗ {meta['error']} (status: {meta.get('status_code')})")

        # Small delay
        time.sleep(0.1)

    print(f"\n=== Summary ===")
    print(f"Total: {len(entries_with_urls)}")
    print(f"Success: {success_count}")
    print(f"Failures: {fail_count}")
    print(f"Cache hits: {cache_hits}")

if __name__ == "__main__":
    main()