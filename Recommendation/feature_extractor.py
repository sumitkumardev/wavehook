# working reccomendation system use in cron jobs after process.py
from pymongo import MongoClient
import numpy as np
import pandas as pd
import librosa, requests, tempfile, os, math
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import MinMaxScaler
import faiss
from datetime import datetime

# ---------------- DB ----------------
client = MongoClient(os.environ["MONGO_URI"])
db = client.musicdb
songs_col = db.songs
vec_col = db.song_vectors
rec_col = db.song_recommendations

TOP_N = 10

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
    except:
        return np.zeros(15)


# ---------------- LOAD SONGS ----------------
songs = list(songs_col.find({}, {"_id": 0}))
df = pd.DataFrame(songs)

df["text"] = df.apply(build_text, axis=1)
df["hook_ratio"] = df.apply(hook_ratio, axis=1)

# ---------------- METADATA VECTORS ----------------
tfidf = TfidfVectorizer(max_features=1000)
meta_vec = tfidf.fit_transform(df["text"]).toarray()

# ---------------- POPULARITY ----------------
scaler = MinMaxScaler()
pop_vec = scaler.fit_transform(df[["playCount"]])

# ---------------- AUDIO VECTORS ----------------
audio_vecs = []
for _, song in df.iterrows():
    url = song["downloadUrl"][2]["url"]
    audio_vecs.append(audio_features(url))

audio_vecs = np.array(audio_vecs)

# ---------------- HOOK VECTOR ----------------
hook_vec = df[["hook_ratio"]].values

# ---------------- FINAL VECTOR (ALL 6 OPTIONS) ----------------
final_vectors = np.hstack([
    meta_vec * 0.4,
    audio_vecs * 0.3,
    hook_vec * 0.1,
    pop_vec * 0.2
]).astype("float32")

# ---------------- STORE VECTORS ----------------
vec_col.delete_many({})
for i, song in df.iterrows():
    vec_col.insert_one({
        "song_id": song["id"],
        "vector": final_vectors[i].tolist()
    })

# ---------------- FAISS INDEX ----------------
dim = final_vectors.shape[1]
index = faiss.IndexFlatL2(dim)
index.add(final_vectors)

# ---------------- BUILD RECOMMENDATIONS ----------------
rec_col.delete_many({})

D, I = index.search(final_vectors, TOP_N + 1)

for idx, song in df.iterrows():
    recs = []
    for j in I[idx][1:]:
        recs.append({"song_id": df.iloc[j]["id"]})

    rec_col.insert_one({
        "song_id": song["id"],
        "recommended": recs,
        "updated_at": datetime.utcnow()
    })

print("✅ Universal recommender built (ALL 6 OPTIONS, FAST MODE)")
