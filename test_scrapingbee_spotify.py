"""
Spotify Metadata Scraper - Gets ALL required fields:
- Artist name
- Song name  
- Image URL
- Duration

Uses multiple approaches to get complete data.
"""

import requests
from bs4 import BeautifulSoup
import re
import json

# ScrapingBee API
SCRAPINGBEE_API_KEY = "2H8R75KT5UR5TWQHOPS2MVBS0C61PVVCOPMC2Y9HGDT55LQ1SMAX5O5ZN6BONP74KJSTM06JF7WK1DVL"


def extract_track_id(url: str) -> str:
    """Extract track ID from Spotify URL"""
    match = re.search(r'track/([a-zA-Z0-9]+)', url)
    return match.group(1) if match else None


def get_spotify_metadata(track_url: str) -> dict:
    """
    Get Spotify track metadata including duration.
    Returns: {song_name, artist_name, image_url, duration, duration_ms}
    """
    
    result = {
        "song_name": None,
        "artist_name": None,
        "image_url": None,
        "duration": None,
        "duration_ms": None,
    }
    
    track_id = extract_track_id(track_url)
    if not track_id:
        print("❌ Could not extract track ID from URL")
        return result
    
    print(f"Track ID: {track_id}")
    
    # APPROACH 1: Scrape the EMBED page (lighter, has metadata)
    embed_url = f"https://open.spotify.com/embed/track/{track_id}"
    print(f"\nApproach 1: Scraping embed page via ScrapingBee...")
    print(f"URL: {embed_url}")
    
    try:
        params = {
            "api_key": SCRAPINGBEE_API_KEY,
            "url": embed_url,
            "render_js": "true",
            "wait": "2000",
        }
        
        resp = requests.get("https://app.scrapingbee.com/api/v1", params=params, timeout=45)
        print(f"Status: {resp.status_code}")
        
        if resp.status_code == 200:
            html = resp.text
            
            # Save HTML for debugging
            with open("debug_embed.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  Saved HTML to debug_embed.html")
            
            # Try to find track data in the page
            # Look for __NEXT_DATA__ or similar React hydration
            soup = BeautifulSoup(html, "html.parser")
            
            # Method 1: Find script with data
            for script in soup.find_all("script"):
                content = script.string or ""
                
                # Look for resource data
                if "Spotify.Entity" in content or '"type":"track"' in content or '"duration":' in content:
                    print("  Found track data in script!")
                    
                    # Extract track name
                    name_match = re.search(r'"name"\s*:\s*"([^"]+)"', content)
                    if name_match:
                        result["song_name"] = name_match.group(1)
                    
                    # Extract duration (can be "duration_ms" or just "duration")
                    dur_match = re.search(r'"duration(?:_ms)?"\s*:\s*(\d+)', content)
                    if dur_match:
                        result["duration_ms"] = int(dur_match.group(1))
                        result["duration"] = format_duration(result["duration_ms"])
                        print(f"  Found duration: {result['duration']}")
                    
                    # Extract artist(s)
                    artist_matches = re.findall(r'"artists"\s*:\s*\[(.*?)\]', content, re.DOTALL)
                    if artist_matches:
                        artist_names = re.findall(r'"name"\s*:\s*"([^"]+)"', artist_matches[0])
                        if artist_names:
                            result["artist_name"] = ", ".join(artist_names)
                    
                    # Extract image
                    img_match = re.search(r'"url"\s*:\s*"(https://[^"]*spotify[^"]*\.(?:jpg|png|jpeg)[^"]*)"', content)
                    if img_match:
                        result["image_url"] = img_match.group(1)
                    
                    break
            
            # Method 2: Look for og:image in meta
            if not result["image_url"]:
                og_img = soup.find("meta", property="og:image")
                if og_img:
                    result["image_url"] = og_img.get("content")
            
            # Method 3: Regex search in full HTML
            if not result["duration_ms"]:
                dur_match = re.search(r'"duration_ms"\s*:\s*(\d+)', html)
                if dur_match:
                    result["duration_ms"] = int(dur_match.group(1))
                    result["duration"] = format_duration(result["duration_ms"])
            
            if not result["song_name"]:
                # Try title tag
                title = soup.find("title")
                if title:
                    result["song_name"] = title.text.split(" - ")[0].strip()
                    
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # APPROACH 2: oEmbed as fallback for image
    if not result["image_url"] or not result["song_name"]:
        print("\nApproach 2: oEmbed fallback...")
        try:
            oembed_url = f"https://open.spotify.com/oembed?url={track_url}"
            resp = requests.get(oembed_url, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                
                if not result["image_url"]:
                    result["image_url"] = data.get("thumbnail_url")
                
                # Parse title for song name and artist
                title = data.get("title", "")
                if title:
                    # Format: "Song Name - song and lyrics by Artist Name"
                    # or "Song Name by Artist Name"
                    if " - song and lyrics by " in title:
                        parts = title.split(" - song and lyrics by ")
                        if not result["song_name"]:
                            result["song_name"] = parts[0].strip()
                        if not result["artist_name"] and len(parts) > 1:
                            result["artist_name"] = parts[1].strip()
                    elif " by " in title:
                        # Split on last " by " to handle songs with "by" in title
                        idx = title.rfind(" by ")
                        if not result["song_name"]:
                            result["song_name"] = title[:idx].strip()
                        if not result["artist_name"]:
                            result["artist_name"] = title[idx+4:].strip()
                    else:
                        if not result["song_name"]:
                            result["song_name"] = title
                
                print(f"  ✅ Got from oEmbed")
                
        except Exception as e:
            print(f"  ❌ oEmbed error: {e}")
    
    return result


def format_duration(ms: int) -> str:
    """Convert milliseconds to readable format (3:30)"""
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


if __name__ == "__main__":
    TEST_URL = "https://open.spotify.com/track/0uE3vuRgjaTBvW6kg3ybdq?si=fbf1858df2c94610"
    
    print("="*60)
    print("SPOTIFY METADATA SCRAPER - Full Test")
    print("="*60)
    print(f"\nTrack: {TEST_URL}\n")
    
    result = get_spotify_metadata(TEST_URL)
    
    print("\n" + "="*60)
    print("FINAL RESULTS")
    print("="*60)
    print(f"  🎵 Song Name:   {result['song_name']}")
    print(f"  👤 Artist:      {result['artist_name']}")
    print(f"  🖼️  Image URL:   {result['image_url'][:60] if result['image_url'] else 'N/A'}...")
    print(f"  ⏱️  Duration:    {result['duration']}")
    
    # Verify we got all required fields
    print("\n" + "-"*40)
    required = ["song_name", "artist_name", "image_url", "duration"]
    all_good = all(result.get(k) for k in required)
    
    if all_good:
        print("✅ SUCCESS! All required fields obtained!")
    else:
        missing = [k for k in required if not result.get(k)]
        print(f"⚠️ Missing fields: {missing}")
