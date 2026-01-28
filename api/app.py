from flask import Flask, jsonify, request, render_template
from pymongo import MongoClient
import random, time, os
from .recommend import recommend

app = Flask(__name__)

MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client.musicdb
songs_col = db.songs
rec_col = db.song_recommendations

CACHE_TTL = 60 * 60 * 24  # 1 day

SESSION = {
    "primary_song": None,
    "in_chain": False,
    "played_cache": {},
    "skip_count": 0
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

def get_primary_song(language=None):
    query = {}
    if language:
        query["language"] = language

    song = list(songs_col.aggregate([
        {"$match": query},
        {"$sample": {"size": 1}}
    ]))[0]

    return song

# ---------------- RECOMMENDED PICK ----------------

def get_recommended_from_primary(primary_id):
    rec = rec_col.find_one({"song_id": primary_id})
    if not rec:
        return None

    for r in rec["recommended"]:
        sid = r["song_id"]
        if is_recently_played(sid):
            continue

        song = songs_col.find_one({"id": sid})
        if song:
            return song

    return None

# ---------------- VECTOR PICK ----------------

def get_vector_recommendation(song_id):
    try:
        recs = recommend(song_id, k=5)
    except:
        return None

    for r in recs:
        sid = r["song_id"]
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
    preferred_lang = request.args.get("preferred_lang") or None

    # ================= FIRST SONG =================
    if SESSION["primary_song"] is None:
        song = get_primary_song(preferred_lang)
        SESSION["primary_song"] = song["id"]
        SESSION["in_chain"] = False
        SESSION["skip_count"] = 0

    # ================= USER LIKED =================
    elif action == "liked":
        SESSION["skip_count"] = 0

        if not SESSION["in_chain"]:
            song = get_recommended_from_primary(SESSION["primary_song"])
            if song:
                SESSION["in_chain"] = True
            else:
                song = get_primary_song(preferred_lang)
                SESSION["primary_song"] = song["id"]
                SESSION["in_chain"] = False
        else:
            song = get_recommended_from_primary(SESSION["primary_song"])
            if not song:
                song = get_primary_song(preferred_lang)
                SESSION["primary_song"] = song["id"]
                SESSION["in_chain"] = False

    # ================= USER SKIPPED =================
    else:
        SESSION["skip_count"] += 1

        # ----- 1st skip → same chain -----
        if SESSION["skip_count"] == 1:
            song = get_recommended_from_primary(SESSION["primary_song"])
            if not song:
                song = get_primary_song(preferred_lang)
                SESSION["primary_song"] = song["id"]
                SESSION["in_chain"] = False

        # ----- 2nd skip → vector similarity -----
        elif SESSION["skip_count"] == 2:
            song = get_vector_recommendation(SESSION["primary_song"])
            if not song:
                song = get_primary_song(preferred_lang)
                SESSION["primary_song"] = song["id"]
                SESSION["in_chain"] = False

        # ----- 3rd skip → random (language filtered) -----
        else:
            song = get_primary_song(preferred_lang)
            SESSION["primary_song"] = song["id"]
            SESSION["in_chain"] = False
            SESSION["skip_count"] = 0

    mark_played(song["id"])
    SESSION["primary_song"] = song["id"]

    return jsonify(song)