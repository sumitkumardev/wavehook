import os
import numpy as np
import faiss
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

    vectors = np.array(vectors).astype("float32")
    return vectors, song_ids

# -----------------------------
# Build FAISS index
# -----------------------------
def build_faiss_index(vectors):
    dim = vectors.shape[1]

    # Normalize for cosine similarity
    faiss.normalize_L2(vectors)

    index = faiss.IndexFlatIP(dim)  # cosine similarity
    index.add(vectors)

    return index

# -----------------------------
# Recommend similar songs
# -----------------------------
def recommend(song_id, k=5):
    vectors, song_ids = load_song_vectors()

    if song_id not in song_ids:
        raise ValueError(f"Song ID {song_id} not found in song_vectors")

    index = build_faiss_index(vectors)

    query_idx = song_ids.index(song_id)
    query_vector = vectors[query_idx].reshape(1, -1)

    distances, indices = index.search(query_vector, k + 1)

    recommendations = []

    for i, idx in enumerate(indices[0]):
        rec_id = song_ids[idx]

        if rec_id == song_id:
            continue

        recommendations.append({
            "song_id": rec_id,
            "similarity": float(distances[0][i])
        })

        if len(recommendations) >= k:
            break

    return recommendations