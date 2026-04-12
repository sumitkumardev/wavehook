import os
import numpy as np
from pymongo import MongoClient

# -----------------------------
# MongoDB Connection
# -----------------------------
MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client.musicdb
vectors_collection = db.song_vectors


# -----------------------------
# In-memory cache
# -----------------------------
VECTORS = None
SONG_IDS = None
NORMS = None
SONG_ID_INDEX = None  # song_id → index lookup (O(1))
LANGUAGES = None      # NEW: language cache


# -----------------------------
# Load vectors ONCE
# -----------------------------
def load_song_vectors():
    global VECTORS, SONG_IDS, NORMS, SONG_ID_INDEX, LANGUAGES

    # already loaded → reuse
    if VECTORS is not None:
        return VECTORS, SONG_IDS, NORMS, LANGUAGES

    vectors = []
    song_ids = []
    languages = []

    cursor = vectors_collection.find({
        "vector": {"$exists": True},
        "language": {"$exists": True}
    })

    for doc in cursor:
        vec = doc.get("vector")
        sid = str(doc.get("song_id"))
        lang = doc.get("language")

        if vec is None:
            continue

        vectors.append(vec)
        song_ids.append(sid)
        languages.append(lang)

    if not vectors:
        raise RuntimeError("No vectors found in song_vectors collection")

    VECTORS = np.array(vectors, dtype="float32")

    # precompute norms once
    NORMS = np.linalg.norm(VECTORS, axis=1)

    SONG_IDS = song_ids
    LANGUAGES = languages

    # Perf: build O(1) lookup dict
    SONG_ID_INDEX = {sid: i for i, sid in enumerate(song_ids)}

    print(f"[recommend] Loaded {len(SONG_IDS)} vectors into RAM")

    return VECTORS, SONG_IDS, NORMS, LANGUAGES


# -----------------------------
# Fast cosine similarity
# -----------------------------
def cosine_similarity_fast(vectors, norms, query_vector):

    q = np.array(query_vector, dtype="float32")
    q_norm = np.linalg.norm(q)

    if q_norm == 0:
        return None

    return np.dot(vectors, q) / (norms * q_norm)


# -----------------------------
# Recommend similar songs
# -----------------------------
def recommend(song_id, k=5, language=None):

    vectors, song_ids, norms, langs = load_song_vectors()

    if song_id not in SONG_ID_INDEX:
        raise ValueError(f"Song ID {song_id} not found in song_vectors")

    idx = SONG_ID_INDEX[song_id]
    query_vector = vectors[idx]

    sims = cosine_similarity_fast(vectors, norms, query_vector)

    if sims is None:
        return []

    # use argpartition O(n)
    n_candidates = min(k + 50, len(sims))

    top_idx = np.argpartition(sims, -n_candidates)[-n_candidates:]

    # sort only candidates
    top_idx = top_idx[np.argsort(sims[top_idx])[::-1]]

    recommendations = []

    for i in top_idx:

        rec_id = song_ids[i]

        # skip self
        if rec_id == song_id:
            continue

        # IMPORTANT: filter by language BEFORE DB call
        if language and langs[i] != language:
            continue

        recommendations.append({
            "song_id": rec_id,
            "similarity": float(sims[i])
        })

        if len(recommendations) >= k:
            break

    return recommendations


# -----------------------------
# Optional manual refresh
# -----------------------------
def refresh_vectors():

    global VECTORS, SONG_IDS, NORMS, SONG_ID_INDEX, LANGUAGES

    VECTORS = None
    SONG_IDS = None
    NORMS = None
    SONG_ID_INDEX = None
    LANGUAGES = None