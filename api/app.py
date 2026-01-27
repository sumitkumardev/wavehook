from flask import Flask, jsonify, request, render_template
from pymongo import MongoClient
import random, time, os
from recommend import recommend

app = Flask(__name__)

MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client.musicdb
songs_col = db.songs
rec_col = db.song_recommendations

# ---------------- CONFIG ----------------

CACHE_TTL = 60 * 60 * 24  # 1 day

SESSION = {
    "primary_song": None,
    "in_chain": False,
    "played_cache": {},
    "skip_count": 0,
    "language_score": {}   # language -> rating (1–10)
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

# ---------------- LANGUAGE RATING ----------------

def get_language(song):
    return song.get("language", "unknown")

def update_language_score(language, delta):
    if language not in SESSION["language_score"]:
        SESSION["language_score"][language] = 5  # start neutral

    SESSION["language_score"][language] += delta
    SESSION["language_score"][language] = max(1, min(10, SESSION["language_score"][language]))

def get_best_language():
    if not SESSION["language_score"]:
        return None
    return max(SESSION["language_score"], key=SESSION["language_score"].get)

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

# ---------------- RECOMMENDED PICK (CHAIN) ----------------

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

# ---------------- VECTOR PICK (FAISS) ----------------

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

    # ================= FIRST SONG =================
    if SESSION["primary_song"] is None:
        song = get_primary_song()
        SESSION["primary_song"] = song["id"]
        SESSION["in_chain"] = False
        SESSION["skip_count"] = 0

    # ================= USER LIKED =================
    elif action == "liked":
        SESSION["skip_count"] = 0  # reset skip count

        lang = get_language(songs_col.find_one({"id": SESSION["primary_song"]}))
        update_language_score(lang, +1)

        if not SESSION["in_chain"]:
            song = get_recommended_from_primary(SESSION["primary_song"])
            if song:
                SESSION["in_chain"] = True
            else:
                song = get_primary_song()
                SESSION["primary_song"] = song["id"]
                SESSION["in_chain"] = False
        else:
            song = get_recommended_from_primary(SESSION["primary_song"])
            if not song:
                song = get_primary_song()
                SESSION["primary_song"] = song["id"]
                SESSION["in_chain"] = False

    # ================= USER SKIPPED =================
    else:
        SESSION["skip_count"] += 1

        current_song = songs_col.find_one({"id": SESSION["primary_song"]})
        if current_song:
            lang = get_language(current_song)
            update_language_score(lang, -1)

        # ----- 1st skip → same chain -----
        if SESSION["skip_count"] == 1:
            song = get_recommended_from_primary(SESSION["primary_song"])
            if not song:
                song = get_primary_song()
                SESSION["primary_song"] = song["id"]
                SESSION["in_chain"] = False

        # ----- 2nd skip → FAISS recommend.py -----
        elif SESSION["skip_count"] == 2:
            song = get_vector_recommendation(SESSION["primary_song"])
            if not song:
                song = get_primary_song()
                SESSION["primary_song"] = song["id"]
                SESSION["in_chain"] = False

        # ----- 3rd skip → random by language rating -----
        else:
            best_lang = get_best_language()
            song = get_primary_song(language=best_lang)
            SESSION["primary_song"] = song["id"]
            SESSION["in_chain"] = False
            SESSION["skip_count"] = 0  # reset after hard reset

    mark_played(song["id"])
    SESSION["primary_song"] = song["id"]

    return jsonify(song)
