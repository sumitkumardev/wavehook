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
# Load vectors from MongoDB
# -----------------------------
def load_song_vectors():
    vectors = []
    song_ids = []

    cursor = vectors_collection.find({"vector": {"$exists": True}})

    for doc in cursor:
        vectors.append(doc["vector"])
        song_ids.append(str(doc["song_id"]))

    if not vectors:
        raise RuntimeError("No vectors found in song_vectors collection")

    vectors = np.array(vectors, dtype="float32")
    return vectors, song_ids

# -----------------------------
# Cosine similarity
# -----------------------------
def cosine_similarity_matrix(vectors, query_vector):
    # Normalize
    vectors_norm = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    query_norm = query_vector / np.linalg.norm(query_vector)

    # Cosine similarity = dot product of normalized vectors
    return np.dot(vectors_norm, query_norm)

# -----------------------------
# Recommend similar songs
# -----------------------------
def recommend(song_id, k=5):
    vectors, song_ids = load_song_vectors()

    if song_id not in song_ids:
        raise ValueError(f"Song ID {song_id} not found in song_vectors")

    query_idx = song_ids.index(song_id)
    query_vector = vectors[query_idx]

    similarities = cosine_similarity_matrix(vectors, query_vector)

    # Get indices sorted by similarity (descending)
    sorted_indices = np.argsort(similarities)[::-1]

    recommendations = []

    for idx in sorted_indices:
        rec_id = song_ids[idx]

        if rec_id == song_id:
            continue

        recommendations.append({
            "song_id": rec_id,
            "similarity": float(similarities[idx])
        })

        if len(recommendations) >= k:
            break

    return recommendations
