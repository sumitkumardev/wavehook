import librosa
import numpy as np


def analyze_audio(audio_path):
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    y = librosa.util.normalize(y)

    # ---------- ENERGY ----------
    energy = librosa.feature.rms(y=y)[0]

    # ---------- BEATS ----------
    beats = librosa.onset.onset_strength(y=y, sr=sr)

    # ---------- STRUCTURE ----------
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    structure = np.mean(np.abs(np.diff(mfcc, axis=1)), axis=0)

    # ---------- ALIGN LENGTHS (🔥 FIX 🔥) ----------
    min_len = min(
        len(energy),
        len(beats),
        len(structure)
    )

    energy = energy[:min_len]
    beats = beats[:min_len]
    structure = structure[:min_len]

    return {
        "energy": energy,
        "beats": beats,
        "structure": structure
    }, sr
