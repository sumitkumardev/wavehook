# Working well sent data to mongo db as per requirement

import requests
import json
import os
from pymongo import MongoClient

BASE_URL = os.environ.get("SAAVN_API_URL")
if BASE_URL is None:
    raise RuntimeError("SAAVN_API_URL environment variable not set")

PLAYLIST_FILE = "playlists.json"

# 🔐 MongoDB connection
client = MongoClient(os.environ["MONGO_URI"])

db = client["musicdb"]
songs_collection = db["songs"]

# ---------------------------------------
def search_playlists(language):
    url = f"{BASE_URL}/search/playlists"
    params = {"query": language}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

# ---------------------------------------
def save_playlist_ids(language):
    response = search_playlists(language)

    playlists = []
    for item in response.get("data", {}).get("results", []):
        playlists.append({
            "playlist_id": item["id"],
            "songCount": item.get("songCount", 0)
        })

    with open(PLAYLIST_FILE, "w") as f:
        json.dump({language: playlists}, f, indent=2)

    print(f"✅ Saved playlists for {language}")

# ---------------------------------------
def fetch_playlist_songs(playlist_id):
    url = f"{BASE_URL}/playlists"
    params = {"id": playlist_id}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

# ---------------------------------------
def save_songs_to_mongodb():
    with open(PLAYLIST_FILE, "r") as f:
        playlists_data = json.load(f)

    for language, playlists in playlists_data.items():
        for playlist in playlists:
            playlist_id = playlist["playlist_id"]
            print(f"🎵 Fetching → {playlist_id}")

            response = fetch_playlist_songs(playlist_id)
            songs = response.get("data", {}).get("songs", [])

            for song in songs:
                song_id = song.get("id")
                if not song_id:
                    continue

                song["_id"] = song_id      # MongoDB primary key
                song["playlist_id"] = playlist_id
                song["language"] = language

                # UPSERT = insert if not exists, update if exists
                songs_collection.update_one(
                    {"_id": song_id},
                    {"$set": song},
                    upsert=True
                )

    print("✅ All songs saved into MongoDB")

# ---------------------------------------
if __name__ == "__main__":
    LANGUAGE = "new-releases"

    save_playlist_ids(LANGUAGE)
    save_songs_to_mongodb()
