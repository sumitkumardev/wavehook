# Working well sent data to mongo db as per requirement
import requests
import os
import time
from pymongo import MongoClient

BASE_URL = os.environ.get("SAAVN_API_URL")
if BASE_URL is None:
    raise RuntimeError("SAAVN_API_URL environment variable not set")

# 🔐 MongoDB connection
client = MongoClient(os.environ["MONGO_URI"])
db = client["musicdb"]
songs_collection = db["songs"]

# ---------------------------------------
def safe_get(url, params=None, retries=3, delay=3):
    """
    Makes GET request safely with retry + delay for rate limit (429)
    """
    for attempt in range(retries):
        response = requests.get(url, params=params)

        if response.status_code == 429:
            wait = delay * (attempt + 1)
            print(f"⚠️ Rate limited. Waiting {wait}s before retry...")
            time.sleep(wait)
            continue

        response.raise_for_status()
        time.sleep(delay)  # slow down every request
        return response.json()

    raise RuntimeError("❌ Failed after too many retries due to rate limit")

# ---------------------------------------
def search_playlists(query):
    url = f"{BASE_URL}/search/playlists"
    params = {"query": query}
    return safe_get(url, params=params)

# ---------------------------------------
def fetch_playlist_songs(playlist_id):
    url = f"{BASE_URL}/playlists"
    params = {"id": playlist_id}
    return safe_get(url, params=params)

# ---------------------------------------
def save_songs_to_mongodb(query):
    playlists_response = search_playlists(query)
    playlists = playlists_response.get("data", {}).get("results", [])

    # 🔒 LIMIT playlists to avoid hitting rate limit
    playlists = playlists[:5]

    for item in playlists:
        playlist_id = item.get("id")
        if not playlist_id:
            continue

        print(f"🎵 Fetching playlist → {playlist_id}")

        response = fetch_playlist_songs(playlist_id)
        songs = response.get("data", {}).get("songs", [])

        for song in songs:
            song_id = song.get("id")
            if not song_id:
                continue

            song["_id"] = song_id
            song["playlist_id"] = playlist_id

            # UPSERT = insert if not exists, update if exists
            songs_collection.update_one(
                {"_id": song_id},
                {"$set": song},
                upsert=True
            )

    print(f"✅ Songs saved for query → {query}")

# ---------------------------------------
def get_language_queries_from_db():
    query_collection = db["language_query"]
    doc = query_collection.find_one()
    if not doc:
        return []

    combined = []
    for key in ["language", "querry", "artist", "year"]:
        values = doc.get(key, [])
        if isinstance(values, list):
            for v in values:
                if v:
                    combined.append(str(v))

    return combined

# ---------------------------------------
if __name__ == "__main__":
    language_list = get_language_queries_from_db()

    for LANGUAGE in language_list:
        print(f"\n🔍 Processing → {LANGUAGE}")
        save_songs_to_mongodb(LANGUAGE)