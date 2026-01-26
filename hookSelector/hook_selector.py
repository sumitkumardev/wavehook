import numpy as np
import librosa


def normalize(x):
    if x is None:
        return None
    x = np.array(x)
    return (x - x.min()) / (x.max() - x.min() + 1e-6)


def sliding_window_scores(signal, window_size):
    scores = []
    for i in range(len(signal) - window_size):
        scores.append(np.mean(signal[i:i + window_size]))
    return np.array(scores)


def select_hooks(
    signals,
    sr,
    hook_duration=12,
    top_n=5,
    min_gap=10
):
    """
    signals: dict from analyzer
    sr: sample rate
    """

    energy = normalize(signals["energy"])
    beats = normalize(signals.get("beats"))
    structure = normalize(signals.get("structure"))

    frames_per_sec = sr / 512
    window_size = int(hook_duration * frames_per_sec)

    # ---------- BASE ENERGY SCORE ----------
    energy_score = sliding_window_scores(energy, window_size)

    # ---------- CONTRAST SCORE ----------
    contrast_score = np.zeros_like(energy_score)
    lookback = int(5 * frames_per_sec)

    for i in range(len(energy_score)):
        prev = energy[max(0, i - lookback):i]
        if len(prev) > 0:
            contrast_score[i] = energy_score[i] - np.mean(prev)

    contrast_score = normalize(contrast_score)

    # ---------- COMBINE SCORES ----------
    final_score = (
        0.5 * normalize(energy_score) +
        0.3 * contrast_score
    )

    if beats is not None:
        beat_score = sliding_window_scores(beats, window_size)
        final_score += 0.2 * normalize(beat_score)

    if structure is not None:
        struct_score = sliding_window_scores(structure, window_size)
        final_score += 0.1 * normalize(struct_score)

    # ---------- PENALIZE INTRO / OUTRO ----------
    song_len_sec = len(energy) / frames_per_sec

    for i in range(len(final_score)):
        t = i / frames_per_sec
        if t < 20 or t > song_len_sec - 20:
            final_score[i] *= 0.3

    # ---------- PICK TOP NON-OVERLAPPING HOOKS ----------
    indices = np.argsort(final_score)[::-1]
    hooks = []

    for idx in indices:
        start = idx / frames_per_sec

        if any(abs(start - h["start"]) < min_gap for h in hooks):
            continue

        hooks.append({
            "start": round(start, 2),
            "end": round(start + hook_duration, 2),
            "score": round(float(final_score[idx]), 3)
        })

        if len(hooks) >= top_n:
            break

    return sorted(hooks, key=lambda x: x["start"])
