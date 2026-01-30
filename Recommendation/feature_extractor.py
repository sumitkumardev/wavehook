# working reccomendation system use in cron jobs after process.py
from pymongo import MongoClient
import numpy as np
import pandas as pd
import librosa, requests, tempfile, os, time
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import MinMaxScaler
import faiss
from datetime import datetime

MODE = "incremental"   # "incremental" or "full"
TOP_N = 10

start_time = time.time()

# ---------------- DB ----------------
client = MongoClient(os.environ["MONGO_URI"])
db = client.musicdb
songs_col = db.songs
vec_col = db.song_vectors
rec_col = db.song_recommendations

print("[STEP] Connected to MongoDB")

# ---------------- HELPERS ----------------
def extract_artists(artists):
    names = []
    for cat in ["primary", "featured", "all"]:
        for a in artists.get(cat, []):
            names.append(a["name"])
    return " ".join(set(names))

def hook_ratio(song):
    h = song.get("hook", {}).get("primehook")
    d = song.get("duration")
    if not h or not d:
        return 0
    m, s = h.split(":")
    return (int(m)*60+int(s)) / d

def build_text(song):
    art = extract_artists(song["artists"])
    return f"{art} {art} {song['language']} {song['language']} {song['label']} {song['year']} {song['type']}"

def audio_features(url):
    try:
        r = requests.get(url, timeout=10)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(r.content)
            path = f.name

        y, sr = librosa.load(path, sr=None)
        os.remove(path)

        mfcc = np.mean(librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13), axis=1)
        tempo = librosa.beat.tempo(y=y, sr=sr)[0]
        centroid = np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))

        return np.concatenate(([tempo, centroid], mfcc))
    except Exception as e:
        print(f"[ERROR] Audio feature failed: {e}")
        return np.zeros(15)

# ---------------- LOAD SONGS ----------------
songs = list(songs_col.find({}, {"_id": 0}))
df = pd.DataFrame(songs)

print(f"[INFO] Total songs in DB: {len(df)}")

df["text"] = df.apply(build_text, axis=1)
df["hook_ratio"] = df.apply(hook_ratio, axis=1)

# ---------------- EXISTING VECTORS ----------------
existing_vec_ids = set(vec_col.distinct("song_id"))
print(f"[INFO] Existing vectors: {len(existing_vec_ids)}")

if MODE == "incremental":
    df_new = df[~df["id"].isin(existing_vec_ids)]
else:
    df_new = df

print(f"[INFO] Songs to vectorize: {len(df_new)}")

# ---------------- BUILD VECTORS ----------------
print("[STEP] Building metadata vectors (TF-IDF)")
tfidf = TfidfVectorizer(max_features=1000)
meta_vec = tfidf.fit_transform(df["text"]).toarray()

print("[STEP] Scaling popularity")
scaler = MinMaxScaler()
pop_vec = scaler.fit_transform(df[["playCount"]])

print("[STEP] Extracting audio features")
audio_vecs = []
for i, (_, song) in enumerate(df_new.iterrows(), 1):
    print(f"[AUDIO] {i}/{len(df_new)} → {song['id']}")
    url = song["downloadUrl"][2]["url"]
    audio_vecs.append(audio_features(url))

audio_vecs = np.array(audio_vecs)
hook_vec = df_new[["hook_ratio"]].values

print("[STEP] Combining final vectors")
final_vectors_new = np.hstack([
    meta_vec[df_new.index] * 0.4,
    audio_vecs * 0.3,
    hook_vec * 0.1,
    pop_vec[df_new.index] * 0.2
]).astype("float32")

# ---------------- STORE NEW VECTORS ----------------
if MODE == "full":
    print("[WARN] FULL mode: clearing old vectors")
    vec_col.delete_many({})

print("[STEP] Storing vectors in DB")
for i, song in df_new.iterrows():
    vec_col.insert_one({
        "song_id": song["id"],
        "vector": final_vectors_new[list(df_new.index).index(i)].tolist(),
        "updated_at": datetime.utcnow()
    })

# ---------------- LOAD ALL VECTORS ----------------
print("[STEP] Loading all vectors")
all_vec_docs = list(vec_col.find({}, {"_id": 0}))
vec_df = pd.DataFrame(all_vec_docs)

vectors = np.vstack(vec_df["vector"].values).astype("float32")

# ---------------- FAISS INDEX ----------------
print("[STEP] Building FAISS index")
dim = vectors.shape[1]
index = faiss.IndexFlatL2(dim)
index.add(vectors)

# ---------------- EXISTING RECOMMENDATIONS ----------------
existing_rec_ids = set(rec_col.distinct("song_id"))
print(f"[INFO] Existing recommendations: {len(existing_rec_ids)}")

if MODE == "incremental":
    df_rec = vec_df[~vec_df["song_id"].isin(existing_rec_ids)]
else:
    print("[WARN] FULL mode: clearing old recommendations")
    rec_col.delete_many({})
    df_rec = vec_df

print(f"[INFO] Songs to recommend: {len(df_rec)}")

# ---------------- BUILD RECOMMENDATIONS ----------------
print("[STEP] Searching nearest neighbors")
D, I = index.search(vectors, TOP_N + 1)

print("[STEP] Writing recommendations")
for i, row in df_rec.iterrows():
    song_id = row["song_id"]
    idx = vec_df.index[vec_df["song_id"] == song_id][0]

    recs = []
    for j in I[idx][1:]:
        recs.append({"song_id": vec_df.iloc[j]["song_id"]})

    rec_col.update_one(
        {"song_id": song_id},
        {"$set": {
            "song_id": song_id,
            "recommended": recs,
            "updated_at": datetime.utcnow()
        }},
        upsert=True
    )

end_time = time.time()
elapsed = round((end_time - start_time) / 60, 2)

print(f"✅ Hybrid recommender built in {MODE.upper()} mode")
print(f"⏱️ Total time: {elapsed} minutes")
