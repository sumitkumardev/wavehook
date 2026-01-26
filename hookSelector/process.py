# process the songs after run.py which generate the hooks

import requests
import tempfile
import os
from pymongo import MongoClient

from analyzer import analyze_audio
from hook_selector import select_hooks


# ----------------------------
# CONFIG
# ----------------------------
MODE = "hook_continue"
# MODE = "rehook"
# ----------------------------


# ----------------------------
# MongoDB
# ----------------------------
client = MongoClient(os.environ["MONGO_URI"])
db = client.musicdb
songs = db.songs


# ----------------------------
# Download MP4
# ----------------------------
def download_mp4(url):
    r = requests.get(url, stream=True, timeout=40)
    r.raise_for_status()

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    for chunk in r.iter_content(8192):
        temp.write(chunk)
    temp.close()

    return temp.name


# ----------------------------
# Seconds → mm:ss
# ----------------------------
def to_timestamp(sec):
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m:02d}:{s:02d}"


# ----------------------------
# Process One Song
# ----------------------------
def process_song(song):
    audio_path = None

    try:
        mp4_url = song["downloadUrl"][2]["url"]
        audio_path = download_mp4(mp4_url)

        signals, sr = analyze_audio(audio_path)
        hooks = select_hooks(signals, sr)

        hook_data = {
            "primehook": to_timestamp(hooks[0]["start"]) if len(hooks) > 0 else None,
            "sechook": to_timestamp(hooks[1]["start"]) if len(hooks) > 1 else None,
            "subhook": to_timestamp(hooks[2]["start"]) if len(hooks) > 2 else None
        }

        songs.update_one(
            {"_id": song["_id"]},
            {"$set": {"hook": hook_data}}
        )

        print(f"✅ Hook stored → {song['_id']}")

    except Exception as e:
        print(f"❌ Error ({song['_id']}): {e}")

    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)


# ----------------------------
# Batch Runner (WITH MODE)
# ----------------------------
def run():
    if MODE == "hook_continue":
        print("▶ MODE: HOOK CONTINUE (skip already hooked)")
        query = {
            "downloadUrl.2": {"$exists": True},
            "hook": {"$exists": False}
        }

    elif MODE == "rehook":
        print("🔁 MODE: REHOOK (overwrite all hooks)")
        query = {
            "downloadUrl.2": {"$exists": True}
        }

    else:
        raise ValueError("Invalid MODE. Use 'hook_continue' or 'rehook'")

    cursor = songs.find(query)

    count = 0
    for song in cursor:
        count += 1
        process_song(song)

    print(f"🏁 Finished. Total processed: {count}")


if __name__ == "__main__":
    run()
