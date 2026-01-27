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
CACHE_TTL = 60 * 60 * 24  # 1 day

SESSION = {
    "primary_song": None,     # current primary song id
    "in_chain": False,        # are we in recommendation chain?
    "played_cache": {}        # song_id: timestamp
}


# ---------------- CACHE ----------------

def is_recently_played(song_id):
    now = time.time()
    expired = [k for k, v in SESSION["played_cache"].items()
               if now - v > CACHE_TTL]
    for k in expired:
        del SESSION["played_cache"][k]
    return song_id in SESSION["played_cache"]


def mark_played(song_id):
    SESSION["played_cache"][song_id] = time.time()


# ---------------- PRIMARY PICK ----------------

def get_primary_song():
    # true random song
    song = list(songs_col.aggregate([{"$sample": {"size": 1}}]))[0]
    return song


# ---------------- RECOMMENDED PICK ----------------

def get_recommended_from_primary(primary_id):
    rec = rec_col.find_one({"song_id": primary_id})
    if not rec:
        return None

    for r in rec["recommended"]:
        sid = r["song_id"]

        # skip already played (server cache)
        if is_recently_played(sid):
            continue

        song = songs_col.find_one({"id": sid})
        if song:
            return song

    return None


# ---------------- ROUTES ----------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/next_song")
def next_song():
    action = request.args.get("action")  # liked / skipped

    # ================= FIRST SONG =================
    if SESSION["primary_song"] is None:
        song = get_primary_song()
        SESSION["primary_song"] = song["id"]
        SESSION["in_chain"] = False

    # ================= USER LIKED =================
    elif action == "liked":
        if not SESSION["in_chain"]:
            # start chain from primary
            song = get_recommended_from_primary(SESSION["primary_song"])
            if song:
                SESSION["in_chain"] = True
            else:
                song = get_primary_song()
                SESSION["primary_song"] = song["id"]
                SESSION["in_chain"] = False
        else:
            # continue inside chain
            song = get_recommended_from_primary(SESSION["primary_song"])
            if not song:
                song = get_primary_song()
                SESSION["primary_song"] = song["id"]
                SESSION["in_chain"] = False

    # ================= USER SKIPPED =================
    else:
        # break chain and go new primary
        song = get_primary_song()
        SESSION["primary_song"] = song["id"]
        SESSION["in_chain"] = False

    # ---------------- CACHE MARK ----------------
    mark_played(song["id"])

    return jsonify(song)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)