#!/usr/bin/env python3
"""
Enrich source_index.json with source URLs from detailed teams.
"""

import json
from pathlib import Path

# Load detailed teams (has source URLs)
detailed_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_teams_detailed.json")
with open(detailed_path) as f:
    detailed = json.load(f)

# Build rank -> URL mapping
url_map = {}
for team in detailed:
    rank = team.get("rank")
    url = team.get("url", "")
    source = team.get("source", "unknown")
    if rank and url:
        url_map[rank] = {"url": url, "source": source}

print(f"Found {len(url_map)} teams with URLs")

# Load source index
source_index_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/source_index.json")
with open(source_index_path) as f:
    source_index = json.load(f)

# Enrich
enriched = 0
for entry in source_index:
    rank = entry.get("rank")
    if rank in url_map:
        entry["source_url"] = url_map[rank]["url"]
        entry["source_platform"] = url_map[rank]["source"]
        enriched += 1

# Save
with open(source_index_path, 'w') as f:
    json.dump(source_index, f, indent=2)

print(f"Enriched {enriched} entries with URLs")

# Show stats
platforms = {}
for e in source_index:
    p = e.get("source_platform", "unknown")
    platforms[p] = platforms.get(p, 0) + 1
print(f"Platform distribution: {platforms}")