from flask import Flask, jsonify, request, render_template
from pymongo import MongoClient
import random, time, os
import numpy as np

from . import recommend as rec_module
from .recommend import (
    recommend,
    load_song_vectors,
    cosine_similarity_fast
)

app = Flask(__name__)

MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client.musicdb
songs_col = db.songs
rec_col = db.song_recommendations

CACHE_TTL = 60 * 60 * 24  # 1 day

# SESSION = {
#     "primary_song": None,
#     "in_chain": False,
#     "played_cache": {},
#     "skip_count": 0
# }

SESSION = {
    "primary_song": None,
    "in_chain": False,
    "played_cache": {},
    "skip_count": 0,

    # NEW
    "taste_vector": None,
    "taste_weight": 0.0
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


# ---------------- Taste Vectors ---------------

def update_taste_vector(song_id, weight=1.0):
    if not song_id:
        return

    vectors, song_ids, _ = load_song_vectors()

    idx_map = rec_module.SONG_ID_INDEX
    if idx_map is None or song_id not in idx_map:
        return

    vec = vectors[idx_map[song_id]]

    # Guard: never allow negative or zero total weight
    if SESSION["taste_vector"] is None:
        if weight <= 0:
            return  # ignore negative feedback before taste exists
        SESSION["taste_vector"] = vec.copy()
        SESSION["taste_weight"] = weight
        return

    new_weight = SESSION["taste_weight"] + weight

    # prevent divide-by-zero or negative collapse
    if new_weight <= 0:
        SESSION["taste_weight"] = 0.0
        return

    SESSION["taste_vector"] = (
        SESSION["taste_vector"] * SESSION["taste_weight"] +
        vec * weight
    ) / new_weight

    SESSION["taste_vector"] = np.nan_to_num(SESSION["taste_vector"])

    SESSION["taste_weight"] = new_weight



# ---------------- PRIMARY PICK ----------------

# Perf 4: projection to fetch only needed fields
SONG_PROJECTION = {"_id": 0}

def get_primary_song(language=None):
    query = {}
    if language:
        query["language"] = language

    result = list(songs_col.aggregate([
        {"$match": query},
        {"$sample": {"size": 1}},
        {"$project": {"_id": 0}}
    ]))

    # Bug 2: guard empty result
    if not result:
        # fallback: try without language filter
        result = list(songs_col.aggregate([
            {"$sample": {"size": 1}},
            {"$project": {"_id": 0}}
        ]))

    if not result:
        return None

    return result[0]

# ---------------- RECOMMENDED PICK ----------------

def get_recommended_from_primary(primary_id, language=None):
    rec = rec_col.find_one({"song_id": primary_id})
    if not rec:
        return None

    for r in rec["recommended"]:
        sid = r["song_id"]

        if is_recently_played(sid):
            continue

        query = {"id": sid}
        if language:
            query["language"] = language

        song = songs_col.find_one(query, SONG_PROJECTION)
        if song:
            return song

    return None

# ---------------- VECTOR PICK ----------------

def get_vector_recommendation(song_id, language=None):
    try:
        recs = recommend(song_id, k=5)
    except Exception:
        return None

    for r in recs:
        sid = r["song_id"]

        if is_recently_played(sid):
            continue

        query = {"id": sid}
        if language:
            query["language"] = language

        song = songs_col.find_one(query, SONG_PROJECTION)
        if song:
            return song

    return None

# ---------------- ROUTES ----------------

@app.route("/")
def home():
    return render_template("index.html")

# NEW ROUTE FOR PREVIOUS BUTTON
@app.route("/song_by_id")
def song_by_id():
    song_id = request.args.get("id")
    if not song_id:
        return jsonify({"error": "missing id"}), 400

    # Bug 4: exclude _id to avoid ObjectId serialization issues
    song = songs_col.find_one({"id": song_id}, {"_id": 0})
    if not song:
        return jsonify({"error": "song not found"}), 404

    return jsonify(song)


# -------------- recommend from taste vector ------------

def recommend_from_taste(language=None):
    # from .recommend import load_song_vectors, cosine_similarity_fast

    tv = SESSION.get("taste_vector")
    if tv is None:
        return None

    vectors, song_ids, norms = load_song_vectors()
    sims = cosine_similarity_fast(vectors, norms, tv)

    if sims is None:
        return None

    sorted_idx = np.argsort(sims)[::-1]

    for i in sorted_idx:
        sid = song_ids[i]

        if is_recently_played(sid):
            continue

        query = {"id": sid}
        if language:
            query["language"] = language

        song = songs_col.find_one(query, SONG_PROJECTION)
        if song:
            return song

    return None



@app.route("/next_song")
def next_song():
    action = request.args.get("action")  # liked / skipped
    preferred_lang = request.args.get("preferred_lang") or None

    song = None

    # ================= FIRST SONG =================
    if SESSION["primary_song"] is None:
        song = get_primary_song(preferred_lang)
        if song:
            SESSION["primary_song"] = song.get("id")
            SESSION["in_chain"] = False
            SESSION["skip_count"] = 0

    elif action == "liked":
        SESSION["skip_count"] = 0

        # reinforce taste
        if SESSION["primary_song"]:
            update_taste_vector(SESSION["primary_song"], weight=1.0)

        # FIRST try taste-based recommendation
        if SESSION["taste_vector"] is not None:
            SESSION["taste_vector"] = np.nan_to_num(SESSION["taste_vector"])

        song = recommend_from_taste(preferred_lang)

        # fallback: chain recommendation
        if not song:
            song = get_recommended_from_primary(
                SESSION["primary_song"], preferred_lang
            )

        # fallback: random primary
        if not song:
            song = get_primary_song(preferred_lang)

    else:
        SESSION["skip_count"] += 1

        # hard skip → penalize taste
        if action == "hard_skip":
            update_taste_vector(SESSION["primary_song"], weight=-0.2)

        # ----- 1st skip → taste-based -----
        if SESSION["skip_count"] == 1:
            song = recommend_from_taste(preferred_lang)
            if not song:
                song = get_recommended_from_primary(SESSION["primary_song"], preferred_lang)

        # ----- 2nd skip → vector similarity -----
        elif SESSION["skip_count"] == 2:
            song = get_vector_recommendation(SESSION["primary_song"], preferred_lang)

        # ----- 3rd skip → random reset -----
        else:
            song = get_primary_song(preferred_lang)
            SESSION["skip_count"] = 0

        # ----------------- increase randomness to prevent skips -----------
        # 15% exploration chance
        if random.random() < 0.15:
            song = get_primary_song(preferred_lang)
            SESSION["skip_count"] = 0

        if not song:
            song = get_primary_song(preferred_lang)

    # Bug 5: defensive check for song and song["id"]
    if not song or "id" not in song:
        return jsonify({"error": "no songs available"}), 503

    mark_played(song["id"])
    SESSION["primary_song"] = song["id"]

    return jsonify(song)
