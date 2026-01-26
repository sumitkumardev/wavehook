# 🎵 WaveHook – Intelligent Music Hook Detection System

WaveHook is an **audio intelligence system** designed to automatically identify the most engaging and catchy segments (“hooks”) of a song using **digital signal processing (DSP)** and **feature-based scoring algorithms**.  
The project focuses on scalability, efficiency, and structured storage of hook metadata for use in music preview platforms, recommendation systems, and short-form content applications.

---

## 📌 Objectives

- Automatically detect hook segments from audio tracks  
- Reduce manual labeling of song highlights  
- Support large-scale batch processing  
- Store hook timestamps in a structured database  
- Enable fast playback of hook segments in downstream applications  

---

---

## ⚙️ Core Components

- **Audio Downloader**  
  Fetches audio streams using remote URLs and prepares them for processing.

- **Preprocessing Module**  
  Normalizes audio (sampling rate, channels) to ensure consistent analysis.

- **Feature Extractor**  
  Computes time-series acoustic features using Librosa and NumPy.

- **Hook Analyzer**  
  Scores segments based on energy, rhythm, and spectral changes.

- **Hook Selector**  
  Identifies the most likely hook candidates (prime, secondary, sub-hook).

- **Database Layer**  
  Stores hook metadata per song ID in MongoDB.

---

## 🧠 Algorithm Overview

WaveHook uses **heuristic scoring** based on extracted audio features instead of heavy deep learning models to ensure:

- Low latency  
- Interpretability  
- Cost efficiency  
- High scalability  

### Extracted Features

- RMS Energy  
- Spectral Centroid  
- Spectral Flux  
- Zero Crossing Rate  
- Tempo (BPM)  
- Beat Strength  
- Onset Strength
