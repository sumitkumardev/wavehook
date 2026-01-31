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

# -----------------------------
# Load vectors ONCE
# -----------------------------
def load_song_vectors():
    global VECTORS, SONG_IDS, NORMS

    # already loaded → reuse
    if VECTORS is not None:
        return VECTORS, SONG_IDS, NORMS

    vectors = []
    song_ids = []

    cursor = vectors_collection.find({"vector": {"$exists": True}})

    for doc in cursor:
        vec = doc.get("vector")
        sid = str(doc.get("song_id"))

        if vec is None:
            continue

        vectors.append(vec)
        song_ids.append(sid)

    if not vectors:
        raise RuntimeError("No vectors found in song_vectors collection")

    VECTORS = np.array(vectors, dtype="float32")

    # precompute norms once
    NORMS = np.linalg.norm(VECTORS, axis=1)

    SONG_IDS = song_ids

    print(f"[recommend] Loaded {len(SONG_IDS)} vectors into RAM")

    return VECTORS, SONG_IDS, NORMS


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
def recommend(song_id, k=5):
    vectors, song_ids, norms = load_song_vectors()

    if song_id not in song_ids:
        raise ValueError(f"Song ID {song_id} not found in song_vectors")

    idx = song_ids.index(song_id)
    query_vector = vectors[idx]

    sims = cosine_similarity_fast(vectors, norms, query_vector)
    if sims is None:
        return []

    # sort by similarity (high → low)
    sorted_idx = np.argsort(sims)[::-1]

    recommendations = []

    for i in sorted_idx:
        rec_id = song_ids[i]

        if rec_id == song_id:
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
    global VECTORS, SONG_IDS, NORMS
    VECTORS = None
    SONG_IDS = None
    NORMS = None