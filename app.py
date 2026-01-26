from flask import Flask, jsonify, request, render_template
from pymongo import MongoClient
import random, time, os

app = Flask(__name__)

MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client.musicdb
songs_col = db.songs
rec_col = db.song_recommendations
vec_col = db.song_vectors

# simple memory (session-like)
# SESSION = {
#     "last_song": None,
#     "used": set()
# }

# new
CACHE_TTL = 60 * 60 * 24  # 1 day (seconds)

SESSION = {
    "last_song": None,
    "played_cache": {}  # song_id: timestamp
}


def get_primary_song():
    # trending / random
    song = songs_col.find().sort("playCount", -1).limit(50)
    song = random.choice(list(song))
    return song

def is_recently_played(song_id):
    now = time.time()

    # remove expired entries
    expired = [k for k, v in SESSION["played_cache"].items()
               if now - v > CACHE_TTL]

    for k in expired:
        del SESSION["played_cache"][k]

    return song_id in SESSION["played_cache"]


def mark_played(song_id):
    SESSION["played_cache"][song_id] = time.time()



def get_recommended_song(base_song_id):
    rec = rec_col.find_one({"song_id": base_song_id})
    if rec:
        for r in rec["recommended"]:
            sid = r["song_id"]

            # 🔥 NEW: skip recently played
            if is_recently_played(sid):
                continue

            song = songs_col.find_one({"id": sid})
            if song:
                return song
    return None



@app.route("/")
def home():
    return render_template("index.html")


@app.route("/next_song")
def next_song():
    action = request.args.get("action")  # liked or skipped

    if SESSION["last_song"] and action == "liked":
        song = get_recommended_song(SESSION["last_song"])
        if not song:
            song = get_primary_song()
    else:
        song = get_primary_song()

    SESSION["last_song"] = song["id"]

    # 🔥 NEW: mark as played
    mark_played(song["id"])

    return jsonify(song)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)