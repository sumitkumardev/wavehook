from flask import Flask, jsonify, request, render_template, g
from pymongo import MongoClient
from collections import deque
import random, time, uuid, os
import numpy as np

from . import recommend as rec_module
from .recommend import (
    recommend,
    recommend_stochastic,
    taste_recommend_stochastic,
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
MAX_SESSIONS = 10000       # memory cap for server-side sessions


# ================ PER-USER SESSION STORE ================
# Each user gets an isolated session via a cookie-tracked ID.
# Replaces the old global SESSION dict that was shared across ALL users.

SESSIONS = {}  # session_id -> session_data


@app.before_request
def load_session():
    # Skip session management for static files
    if request.path.startswith("/static/"):
        return

    sid = request.cookies.get("wavehook_sid")

    if sid and sid in SESSIONS:
        g.session = SESSIONS[sid]
        g.session_id = sid
    else:
        # Evict oldest session if at memory cap
        if len(SESSIONS) >= MAX_SESSIONS:
            oldest_key = next(iter(SESSIONS))
            del SESSIONS[oldest_key]

        sid = str(uuid.uuid4())
        g.session = {
            "primary_song": None,
            "played_cache": {},
            "skip_count": 0,
            "taste_vector": None,
            "taste_weight": 0.0,
            "recent_vectors": deque(maxlen=10),
        }
        SESSIONS[sid] = g.session
        g.session_id = sid


@app.after_request
def save_session_cookie(response):
    if hasattr(g, "session_id"):
        response.set_cookie(
            "wavehook_sid",
            g.session_id,
            max_age=86400 * 30,
            httponly=True,
            samesite="Lax",
        )
    return response


# ================ INPUT VALIDATION ================

def sanitize_language(lang):
    """Allow only short alphabetic language names."""
    if not lang:
        return None
    lang = lang.strip().lower()
    if not lang.isalpha() or len(lang) > 30:
        return None
    return lang


# ================ PROJECTION ================
# Only return fields the frontend actually needs.
# Reduces response payload significantly.

SONG_PROJECTION = {
    "_id": 0,
    "id": 1,
    "name": 1,
    "artists": 1,
    "image": 1,
    "downloadUrl": 1,
    "hook": 1,
    "language": 1,
}


# ---------------- CACHE ----------------

def is_recently_played(song_id):

    now = time.time()

    expired = [
        k for k, v in g.session["played_cache"].items()
        if now - v > CACHE_TTL
    ]

    for k in expired:
        del g.session["played_cache"][k]

    return song_id in g.session["played_cache"]


def mark_played(song_id):

    g.session["played_cache"][song_id] = time.time()
    _track_recent_vector(song_id)


def _track_recent_vector(song_id):
    """Push the song's embedding onto the recent_vectors deque for diversity tracking."""
    if not song_id:
        return

    vectors, song_ids, _, _ = load_song_vectors()
    idx_map = rec_module.SONG_ID_INDEX

    if idx_map is None or song_id not in idx_map:
        return

    vec = vectors[idx_map[song_id]].tolist()  # store as plain list in deque
    g.session["recent_vectors"].append(vec)


# ---------------- Taste Vectors ---------------

TASTE_DECAY = 0.85  # Recent likes weigh ~6× more than likes from 10 songs ago


def update_taste_vector(song_id, weight=1.0):

    if not song_id:
        return

    vectors, song_ids, _, _ = load_song_vectors()

    idx_map = rec_module.SONG_ID_INDEX

    if idx_map is None or song_id not in idx_map:
        return

    vec = vectors[idx_map[song_id]]

    if g.session["taste_vector"] is None:

        if weight <= 0:
            return

        g.session["taste_vector"] = vec.copy()
        g.session["taste_weight"] = weight
        return

    # Exponential recency decay: reduce influence of older interactions
    decayed_weight = g.session["taste_weight"] * TASTE_DECAY

    new_weight = decayed_weight + weight

    if new_weight <= 0:
        g.session["taste_weight"] = 0.0
        g.session["taste_vector"] = None  # Reset vector when weight drops to zero
        return

    g.session["taste_vector"] = (
        g.session["taste_vector"] * decayed_weight
        + vec * weight
    ) / new_weight

    g.session["taste_vector"] = np.nan_to_num(
        g.session["taste_vector"]
    )

    g.session["taste_weight"] = new_weight



# ---------------- PRIMARY PICK ----------------

def get_primary_song(language=None):

    query = {}

    if language:
        query["language"] = language


    result = list(

        songs_col.aggregate([

            {"$match": query},

            {"$sample": {"size": 1}},

            {"$project": SONG_PROJECTION}

        ])

    )


    if not result:

        result = list(

            songs_col.aggregate([

                {"$sample": {"size": 1}},

                {"$project": SONG_PROJECTION}

            ])

        )


    if not result:
        return None


    return result[0]


# ---------------- RECOMMENDED PICK ----------------

def get_recommended_from_primary(primary_id, language=None):

    rec = rec_col.find_one({"song_id": primary_id})

    if not rec:
        return None


    # Shuffle to break deterministic ordering across sessions
    candidates = list(rec["recommended"])
    random.shuffle(candidates)

    for r in candidates:

        sid = r["song_id"]

        if is_recently_played(sid):
            continue


        query = {"id": sid}

        if language:
            query["language"] = language


        song = songs_col.find_one(
            query,
            SONG_PROJECTION
        )

        if song:
            return song


    return None



# ---------------- VECTOR PICK ----------------

def get_vector_recommendation(song_id, language=None):

    excluded = set(g.session["played_cache"].keys())
    recent_vecs = list(g.session.get("recent_vectors", []))

    try:
        recs = recommend_stochastic(
            song_id,
            k=5,
            language=language,
            excluded_ids=excluded,
            recent_vectors=recent_vecs,
            temperature=0.35
        )
    except Exception:
        return None

    if not recs:
        return None

    # Batch DB lookup
    candidate_ids = [r["song_id"] for r in recs]
    results = {
        doc["id"]: doc
        for doc in songs_col.find(
            {"id": {"$in": candidate_ids}},
            SONG_PROJECTION
        )
    }

    for sid in candidate_ids:
        if sid in results:
            return results[sid]

    return None



# -------------- recommend from taste vector (batched) ------------

def recommend_from_taste(language=None, temperature=0.35):

    tv = g.session.get("taste_vector")

    if tv is None:
        return None

    excluded = set(g.session["played_cache"].keys())
    if g.session["primary_song"]:
        excluded.add(g.session["primary_song"])

    recent_vecs = list(g.session.get("recent_vectors", []))

    try:
        recs = taste_recommend_stochastic(
            tv,
            k=5,
            language=language,
            excluded_ids=excluded,
            recent_vectors=recent_vecs,
            temperature=temperature
        )
    except Exception:
        return None

    if not recs:
        return None

    # Single batch DB query
    candidate_ids = [r["song_id"] for r in recs]
    results = {
        doc["id"]: doc
        for doc in songs_col.find(
            {"id": {"$in": candidate_ids}},
            SONG_PROJECTION
        )
    }

    # Return first match in priority order
    for sid in candidate_ids:
        if sid in results:
            return results[sid]

    return None



# ---------------- ROUTES ----------------

@app.route("/")
def home():

    return render_template("index.html")



@app.route("/song_by_id")
def song_by_id():

    song_id = request.args.get("id")

    if not song_id:
        return jsonify({"error": "missing id"}), 400


    song = songs_col.find_one(
        {"id": song_id},
        SONG_PROJECTION
    )


    if not song:
        return jsonify({"error": "song not found"}), 404


    return jsonify(song)



@app.route("/next_song")
def next_song():

    action = request.args.get("action")

    preferred_lang = sanitize_language(
        request.args.get("preferred_lang")
    )


    song = None


    # ================= FIRST SONG =================

    if g.session["primary_song"] is None:

        song = get_primary_song(preferred_lang)

        if song:

            g.session["primary_song"] = song.get("id")

            g.session["skip_count"] = 0



    elif action == "liked":

        g.session["skip_count"] = 0


        if g.session["primary_song"]:

            update_taste_vector(
                g.session["primary_song"],
                weight=1.0
            )


        song = recommend_from_taste(
            preferred_lang
        )


        if not song:

            song = get_recommended_from_primary(
                g.session["primary_song"],
                preferred_lang
            )


        if not song:

            song = get_primary_song(
                preferred_lang
            )



    elif action == "prefetch":

        # Neutral fetch — no taste vector modification
        # Warmer temperature (0.5) for more diversity in the prefetch buffer
        song = recommend_from_taste(preferred_lang, temperature=0.5)

        if not song:
            song = get_recommended_from_primary(
                g.session["primary_song"],
                preferred_lang
            )

        if not song:
            song = get_primary_song(preferred_lang)


    else:

        g.session["skip_count"] += 1


        if action == "hard_skip":

            update_taste_vector(
                g.session["primary_song"],
                weight=-0.2
            )


        # Exploration: decide EARLY to skip expensive computation
        if random.random() < 0.15:

            song = get_primary_song(preferred_lang)

            g.session["skip_count"] = 0


        elif g.session["skip_count"] == 1:

            song = recommend_from_taste(
                preferred_lang
            )


            if not song:

                song = get_recommended_from_primary(
                    g.session["primary_song"],
                    preferred_lang
                )


        elif g.session["skip_count"] == 2:

            song = get_vector_recommendation(
                g.session["primary_song"],
                preferred_lang
            )


        else:

            song = get_primary_song(
                preferred_lang
            )

            g.session["skip_count"] = 0


        if not song:

            song = get_primary_song(
                preferred_lang
            )



    if not song or "id" not in song:

        return jsonify(
            {"error": "no songs available"}
        ), 503


    mark_played(song["id"])

    # Don't update primary_song for prefetch — user hasn't seen it yet
    if action != "prefetch":
        g.session["primary_song"] = song["id"]


    return jsonify(song)


@app.route("/report_action")
def report_action():
    """Lightweight taste-feedback endpoint.

    Called fire-and-forget when the user swipes to an already-prefetched
    slide.  Updates the taste vector / skip count without returning a song.
    """
    action = request.args.get("action")
    song_id = request.args.get("song_id")
    preferred_lang = sanitize_language(
        request.args.get("preferred_lang")
    )

    if not song_id and g.session.get("primary_song"):
        song_id = g.session["primary_song"]

    if not song_id:
        return jsonify({"ok": True})

    if action == "liked":
        g.session["skip_count"] = 0
        update_taste_vector(song_id, weight=1.0)
    elif action == "hard_skip":
        g.session["skip_count"] += 1
        update_taste_vector(song_id, weight=-0.2)
    elif action == "skipped":
        g.session["skip_count"] += 1

    # Update primary to the song the user is currently on
    g.session["primary_song"] = song_id

    return jsonify({"ok": True})