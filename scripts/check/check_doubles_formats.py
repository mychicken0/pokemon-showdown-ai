#!/usr/bin/env python3
import os
import re

def to_id_str(name: str) -> str:
    """Normalize names to Showdown IDs (strip non-alphanumeric, lowercase)."""
    return "".join([c for c in name if c.isalnum()]).lower()

def main():
    formats_path = "../pokemon-showdown/config/formats.ts"
    print(f"Checking for doubles formats from local file: {formats_path}...")
    
    doubles_formats = []
    
    # Try parsing formats.ts if it exists
    if os.path.exists(formats_path):
        try:
            with open(formats_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Simple regex search for format blocks containing gameType: 'doubles'
            # Look for matches that start with a brace, contain a name, gameType: 'doubles', and close
            # Since formats.ts is large, let's find all chunks between { and }
            # (non-greedy, but allowing nested braces is hard with regex; a simpler approach is line by line tracking)
            lines = content.splitlines()
            current_name = None
            is_doubles = False
            
            for line in lines:
                # Check for name field
                name_match = re.search(r'name:\s*[\'"]([^\'"]+)[\'"]', line)
                if name_match:
                    current_name = name_match.group(1)
                    is_doubles = False # reset for new format entry
                    
                # Check for gameType: 'doubles'
                if current_name and re.search(r'gameType:\s*[\'"]doubles[\'"]', line):
                    is_doubles = True
                    
                # End of a format entry (indicated by a closing brace on its own line or comma)
                if current_name and is_doubles:
                    doubles_formats.append((current_name, to_id_str(current_name)))
                    current_name = None
                    is_doubles = False
                    
        except Exception as e:
            print(f"Warning: Could not parse formats.ts due to: {e}")
    else:
        print(f"Warning: local formats.ts file not found at {formats_path}")

    # Remove duplicates and filter to valid looking format entries
    unique_doubles = []
    seen = set()
    for name, fid in doubles_formats:
        if fid not in seen:
            seen.add(fid)
            unique_doubles.append((name, fid))

    print("\n--- Available Local Doubles Formats ---")
    if unique_doubles:
        for name, fid in unique_doubles:
            print(f"- {name} (ID: {fid})")
    else:
        print("No doubles formats parsed successfully from formats.ts.")

    print("\n--- Recommended Format IDs ---")
    # Always print recommended fallback formats as requested
    fallbacks = [
        ("gen9doublesrandombattle", "[Gen 9] Random Doubles Battle"),
        ("gen9doublesou", "[Gen 9] Doubles OU"),
        ("gen9vgc2025regi", "[Gen 9] VGC 2025 Reg I")
    ]
    for fid, name in fallbacks:
        matched_str = " (Confirmed Available)" if fid in seen else " (Recommended Fallback)"
        print(f"- {fid} : {name}{matched_str}")

if __name__ == "__main__":
    main()
