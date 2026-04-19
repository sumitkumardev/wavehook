import os
import time
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
LANGUAGES = None      # language cache

_vectors_loaded_at = 0
VECTOR_CACHE_TTL = 60 * 60  # 1 hour — auto-refresh picks up new songs


# -----------------------------
# Load vectors ONCE (with TTL refresh)
# -----------------------------
def load_song_vectors():
    global VECTORS, SONG_IDS, NORMS, SONG_ID_INDEX, LANGUAGES, _vectors_loaded_at

    now = time.time()

    # already loaded and still fresh → reuse
    if VECTORS is not None and (now - _vectors_loaded_at) < VECTOR_CACHE_TTL:
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

    _vectors_loaded_at = now

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

    # Guard against zero-norm vectors to prevent Inf/NaN
    safe_norms = np.maximum(norms, 1e-10)

    return np.dot(vectors, q) / (safe_norms * q_norm)


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
# Softmax-temperature sampling
# -----------------------------
def _softmax_sample(scores, temperature=0.35, k=1):
    """Pick k indices from *scores* using softmax-temperature weighted random sampling."""

    if len(scores) == 0:
        return []

    scores = np.array(scores, dtype="float32")

    # Temperature scaling
    scaled = scores / max(temperature, 1e-8)

    # Numerical stability: subtract max before exp
    scaled -= scaled.max()

    exp_scores = np.exp(scaled)
    probs = exp_scores / exp_scores.sum()

    # Guard against NaN (e.g. all-zero input)
    if np.any(np.isnan(probs)):
        probs = np.ones_like(probs) / len(probs)

    k = min(k, len(probs))
    chosen = np.random.choice(len(probs), size=k, replace=False, p=probs)
    return chosen.tolist()


# -----------------------------
# Diversity penalty
# -----------------------------
def _apply_diversity_penalty(sims, indices, vectors, recent_vectors,
                             threshold=0.85, penalty=0.5):
    """Reduce scores for candidates whose embedding is > *threshold*
    cosine-similar to any vector in *recent_vectors*."""

    adjusted = sims[indices].copy()

    if not recent_vectors or len(recent_vectors) == 0:
        return adjusted

    recent_mat = np.array(recent_vectors, dtype="float32")
    recent_norms = np.linalg.norm(recent_mat, axis=1)
    safe_recent_norms = np.maximum(recent_norms, 1e-10)

    for j, idx in enumerate(indices):
        vec = vectors[idx]
        vec_norm = np.linalg.norm(vec)
        if vec_norm < 1e-10:
            continue

        cos_sims = np.dot(recent_mat, vec) / (safe_recent_norms * vec_norm)

        if np.any(cos_sims > threshold):
            adjusted[j] *= penalty

    return adjusted


# -----------------------------
# Stochastic song-based recommendation
# -----------------------------
def recommend_stochastic(song_id, k=5, language=None,
                         excluded_ids=None, recent_vectors=None,
                         temperature=0.35):
    """Like recommend(), but samples from top candidates using softmax
    instead of always returning the top-ranked results."""

    vectors, song_ids, norms, langs = load_song_vectors()

    if song_id not in SONG_ID_INDEX:
        raise ValueError(f"Song ID {song_id} not found in song_vectors")

    idx = SONG_ID_INDEX[song_id]
    query_vector = vectors[idx]

    sims = cosine_similarity_fast(vectors, norms, query_vector)
    if sims is None:
        return []

    excluded = excluded_ids or set()

    # Larger pool for sampling diversity
    pool_size = min(k + 50, len(sims))
    top_idx = np.argpartition(sims, -pool_size)[-pool_size:]

    # Filter: self, excluded, wrong language
    filtered = []
    for i in top_idx:
        sid = song_ids[i]
        if sid == song_id:
            continue
        if sid in excluded:
            continue
        if language and langs[i] != language:
            continue
        filtered.append(i)

    if not filtered:
        return []

    filtered = np.array(filtered)

    # Diversity penalty against recently played
    adjusted_scores = _apply_diversity_penalty(
        sims, filtered, vectors, recent_vectors
    )

    # Softmax-temperature sample
    chosen_local = _softmax_sample(
        adjusted_scores, temperature=temperature,
        k=min(k, len(filtered))
    )

    recommendations = []
    for local_idx in chosen_local:
        global_idx = filtered[local_idx]
        recommendations.append({
            "song_id": song_ids[global_idx],
            "similarity": float(sims[global_idx])
        })

    return recommendations


# -----------------------------
# Stochastic taste-vector recommendation
# -----------------------------
def taste_recommend_stochastic(taste_vector, k=5, language=None,
                               excluded_ids=None, recent_vectors=None,
                               temperature=0.35):
    """Recommend songs closest to a taste vector using stochastic sampling."""

    vectors, song_ids, norms, langs = load_song_vectors()

    sims = cosine_similarity_fast(vectors, norms, taste_vector)
    if sims is None:
        return []

    excluded = excluded_ids or set()

    pool_size = min(k + 50, len(sims))
    top_idx = np.argpartition(sims, -pool_size)[-pool_size:]

    filtered = []
    for i in top_idx:
        sid = song_ids[i]
        if sid in excluded:
            continue
        if language and langs[i] != language:
            continue
        filtered.append(i)

    if not filtered:
        return []

    filtered = np.array(filtered)

    adjusted_scores = _apply_diversity_penalty(
        sims, filtered, vectors, recent_vectors
    )

    chosen_local = _softmax_sample(
        adjusted_scores, temperature=temperature,
        k=min(k, len(filtered))
    )

    recommendations = []
    for local_idx in chosen_local:
        global_idx = filtered[local_idx]
        recommendations.append({
            "song_id": song_ids[global_idx],
            "similarity": float(sims[global_idx])
        })

    return recommendations


# -----------------------------
# Optional manual refresh
# -----------------------------
def refresh_vectors():

    global VECTORS, SONG_IDS, NORMS, SONG_ID_INDEX, LANGUAGES, _vectors_loaded_at

    VECTORS = None
    SONG_IDS = None
    NORMS = None
    SONG_ID_INDEX = None
    LANGUAGES = None
    _vectors_loaded_at = 0