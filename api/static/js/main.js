// =============================================
//  WAVEHOOK — CAROUSEL MUSIC PLAYER
//  Each song = persistent slide element (like YouTube Shorts)
//  Back/forward through existing slides is instant (no network)
// =============================================

/* ===== CONSTANTS ===== */
const CACHE_KEY = "played_songs_cache";
const LANG_KEY = "language_score";
const HISTORY_KEY = "played_history";
const SETUP_DONE_KEY = "wavehook_setup_done";
const TRANSITION_MS = 400;
const CROSSFADE_MS = 250;   // simultaneous fade duration
const MAX_SLIDES = 20;      // memory cap
const MAX_RETRY = 3;
const PREFETCH_AHEAD = 2;   // keep 2 slides ready ahead

/* ===== CAROUSEL STATE ===== */
const carousel = document.getElementById("carousel");
const slideTemplate = document.getElementById("slide-template");

const slides = [];           // [{el, audio, songId, song, hooks, hookIndex}]
let currentSlideIndex = -1;
let isTransitioning = false;
let startTime = 0;
let offsetY = 0;
let startY = 0;


// =============================================
//  LOADING INDICATOR (injected dynamically)
// =============================================

const _loaderStyle = document.createElement("style");
_loaderStyle.textContent = `
@keyframes wh-loader-spin { to { transform: rotate(360deg); } }
#loading-indicator {
    display: none;
    position: fixed;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    z-index: 9999;
    pointer-events: none;
}
#loading-indicator .spinner {
    width: 36px; height: 36px;
    border: 3px solid rgba(255,255,255,0.15);
    border-top-color: rgba(255,255,255,0.8);
    border-radius: 50%;
    animation: wh-loader-spin 0.7s linear infinite;
}`;
document.head.appendChild(_loaderStyle);

const _loader = document.createElement("div");
_loader.id = "loading-indicator";
_loader.innerHTML = '<div class="spinner"></div>';
document.body.appendChild(_loader);

function showLoader() { _loader.style.display = "flex"; }
function hideLoader() { _loader.style.display = "none"; }


// =============================================
//  UTILITY FUNCTIONS
// =============================================

function decodeHTMLEntities(text) {
    const parser = new DOMParser();
    return parser.parseFromString(`<!doctype html><body>${text}`, 'text/html').body.textContent;
}

function parseTime(t) {
    if (!t) return 0;
    const [m, s] = t.split(":");
    return parseInt(m) * 60 + parseInt(s);
}

function extractHooks(song) {
    const list = [];
    if (song.hook?.primehook) list.push(song.hook.primehook);
    if (song.hook?.sechook) list.push(song.hook.sechook);
    if (song.hook?.subhook) list.push(song.hook.subhook);
    return list.length ? list : ["00:00"];
}

function applyMarqueeToTitle(titleEl, text) {
    if (text.length <= 20) {
        titleEl.classList.remove("animate");
        titleEl.innerText = text;
        return;
    }
    const separator = "\u00A0\u00A0♪\u00A0\u00A0";
    const repeated = text + separator;
    titleEl.innerHTML = `
    <span class="marquee-track">
      <span class="marquee-item">${repeated}</span>
      <span class="marquee-item">${repeated}</span>
    </span>`;
    titleEl.classList.add("animate");
}


// =============================================
//  SAFE DATA ACCESS HELPERS
// =============================================

function getSafeCoverUrl(song) {
    return song.image?.[2]?.url
        || song.image?.[1]?.url
        || song.image?.[0]?.url
        || '';
}

function getSafeAudioUrl(song) {
    return song.downloadUrl?.[4]?.url
        || song.downloadUrl?.[3]?.url
        || song.downloadUrl?.[2]?.url
        || song.downloadUrl?.[1]?.url
        || song.downloadUrl?.[0]?.url
        || '';
}


// =============================================
//  FADE VOLUME (per-audio, WeakMap-tracked)
// =============================================
const fadeIntervals = new WeakMap();

function fadeVolume(audioEl, targetVolume, duration = 250) {
    if (!audioEl) return;

    const existing = fadeIntervals.get(audioEl);
    if (existing) clearInterval(existing);

    const steps = 15;
    const stepTime = duration / steps;
    let vol = audioEl.volume;
    const delta = (targetVolume - vol) / steps;

    if (delta === 0) { audioEl.volume = targetVolume; return; }

    const interval = setInterval(() => {
        vol += delta;
        audioEl.volume = Math.min(Math.max(vol, 0), 1);

        if ((delta > 0 && audioEl.volume >= targetVolume) ||
            (delta < 0 && audioEl.volume <= targetVolume)) {
            clearInterval(interval);
            fadeIntervals.delete(audioEl);
            audioEl.volume = Math.min(Math.max(targetVolume, 0), 1);
        }
    }, stepTime);

    fadeIntervals.set(audioEl, interval);
}


// =============================================
//  GRADIENT FROM COVER ART
// =============================================

function extractPalette(img) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    canvas.width = w;
    canvas.height = h;
    ctx.drawImage(img, 0, 0, w, h);
    const data = ctx.getImageData(0, 0, w, h).data;

    const colors = [];
    for (let i = 0; i < data.length; i += 120) {
        colors.push([data[i], data[i + 1], data[i + 2]]);
    }
    return [
        colors[0],
        colors[Math.floor(colors.length / 2)],
        colors[colors.length - 1]
    ];
}

function setPremiumGradient(img) {
    try {
        const palette = extractPalette(img);
        const dark = c => `rgb(${c[0] * 0.25}, ${c[1] * 0.25}, ${c[2] * 0.25})`;
        document.body.style.background =
            `linear-gradient(120deg, ${dark(palette[0])}, ${dark(palette[1])}, ${dark(palette[2])})`;
    } catch (e) { /* CORS or empty — ignore */ }
}


// =============================================
//  MEDIA SESSION (lock screen controls)
// =============================================

function updateMediaSession(song) {
    if (!("mediaSession" in navigator)) return;

    const artworkUrl = getSafeCoverUrl(song);

    navigator.mediaSession.metadata = new MediaMetadata({
        title: decodeHTMLEntities(song.name),
        artist: song.language || "WaveHook",
        album: "WaveHook",
        artwork: artworkUrl
            ? [{ src: artworkUrl, sizes: "256x256", type: "image/png" }]
            : []
    });

    navigator.mediaSession.setActionHandler("play", () => {
        slides[currentSlideIndex]?.audio?.play();
    });
    navigator.mediaSession.setActionHandler("pause", () => {
        slides[currentSlideIndex]?.audio?.pause();
    });
    navigator.mediaSession.setActionHandler("nexttrack", () => snapNext());
    navigator.mediaSession.setActionHandler("previoustrack", () => snapPrevious());
}

function updatePositionState() {
    const audio = slides[currentSlideIndex]?.audio;
    if (audio && "mediaSession" in navigator && !isNaN(audio.duration)) {
        navigator.mediaSession.setPositionState({
            duration: audio.duration,
            playbackRate: audio.playbackRate,
            position: audio.currentTime
        });
    }
}


// =============================================
//  LANGUAGE STORAGE
// =============================================

function getLangScore() { return JSON.parse(localStorage.getItem(LANG_KEY) || "{}"); }
function saveLangScore(obj) { localStorage.setItem(LANG_KEY, JSON.stringify(obj)); }
function updateLangScore(lang, delta) {
    const s = getLangScore();
    if (!s[lang]) s[lang] = 5;
    s[lang] = Math.max(1, Math.min(10, s[lang] + delta));
    saveLangScore(s);
}
function getBestLanguage() {
    const s = getLangScore();
    let best = null, val = -1;
    for (const k in s) { if (s[k] > val) { val = s[k]; best = k; } }
    return best;
}

function saveLanguagePreference() {
    const checks = document.querySelectorAll("#langPanel input:checked");
    const selected = [...checks].map(c => c.value);

    if (selected.includes("all") || !selected.length) {
        saveLangScore({});
    } else {
        const scores = {};
        selected.forEach(l => scores[l] = 8);
        saveLangScore(scores);
    }

    localStorage.setItem(SETUP_DONE_KEY, "1");
    document.getElementById("langPanel").style.display = "none";
    loadFirstSong();
}

function checkFirstTime() {
    document.getElementById("langPanel").style.display = "flex";
}


// =============================================
//  CACHE & HISTORY
//  In-memory Set mirrors localStorage for O(1) lookups
//  without repeated JSON.parse on every check.
// =============================================

const _cacheSet = new Set(
    Object.keys(JSON.parse(localStorage.getItem(CACHE_KEY) || "{}"))
);

function isInCache(id) { return _cacheSet.has(id); }

function markInCache(id) {
    _cacheSet.add(id);
    const c = JSON.parse(localStorage.getItem(CACHE_KEY) || "{}");
    c[id] = Date.now();
    localStorage.setItem(CACHE_KEY, JSON.stringify(c));
}

function getHistory() { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); }
function saveHistory(arr) { localStorage.setItem(HISTORY_KEY, JSON.stringify(arr)); }

function pushHistory(songId) {
    const history = getHistory();
    if (history.length === 0 || history[history.length - 1] !== songId) {
        history.push(songId);
        saveHistory(history);
    }
}


// =============================================
//  CREATE SLIDE (one per song, persists in DOM)
// =============================================

function createSlide(song) {
    const clone = slideTemplate.content.cloneNode(true);
    const el = clone.querySelector(".slide");

    const cover = el.querySelector(".cover-img");
    const titleEl = el.querySelector(".song-title");
    const artistEl = el.querySelector(".song-artist");
    const audio = el.querySelector(".song-audio");
    const progressBar = el.querySelector(".song-progress");
    const seekBar = el.querySelector(".song-seek");
    const currentTimeEl = el.querySelector(".song-current-time");
    const durationEl = el.querySelector(".song-duration");
    const playBtn = el.querySelector(".play-btn");
    const pauseBtn = el.querySelector(".pause-btn");
    const nextBtn = el.querySelector(".next-btn");
    const prevBtn = el.querySelector(".prev-btn");
    const hookBtn = el.querySelector(".button-hook");

    // --- Populate (with null-safe access) ---
    applyMarqueeToTitle(titleEl, decodeHTMLEntities(song.name));

    const artists = song.artists?.primary?.map(a => decodeHTMLEntities(a.name)) || [];
    artistEl.innerText =
        artists.length > 2
            ? artists.slice(0, 2).join(", ") + " & more"
            : artists.join(", ") || "Unknown Artist";

    cover.src = getSafeCoverUrl(song);

    // --- Audio: preload so crossfade is instant ---
    audio.src = getSafeAudioUrl(song);

    const slideHooks = extractHooks(song);
    let hookIndex = 0;

    // Seek to first hook as soon as metadata loads
    audio.addEventListener("loadedmetadata", () => {
        if (audio.currentTime < 1) {
            audio.currentTime = parseTime(slideHooks[0]);
        }
        const mins = Math.floor(audio.duration / 60);
        const secs = Math.floor(audio.duration % 60);
        durationEl.textContent = `${mins}:${secs < 10 ? "0" : ""}${secs}`;
    }, { once: true });

    // --- Time update & progress ---
    audio.addEventListener("timeupdate", () => {
        if (!audio.duration) return;
        const cm = Math.floor(audio.currentTime / 60);
        const cs = Math.floor(audio.currentTime % 60);
        currentTimeEl.textContent = `${cm}:${cs < 10 ? "0" : ""}${cs}`;
        const p = audio.currentTime / audio.duration;
        progressBar.style.width = `${p * 100}%`;
        seekBar.value = p * 100;

        // media session position
        if (slides[currentSlideIndex]?.el === el) {
            updatePositionState();
        }
    });

    // --- Song ended → auto next ---
    audio.addEventListener("ended", () => {
        if (slides[currentSlideIndex]?.el === el) {
            snapNext();
        }
    });

    // --- Play/Pause UI sync (no feedback loop) ---
    audio.addEventListener("play", () => {
        playBtn.style.display = "none";
        pauseBtn.style.display = "inline-flex";
    });
    audio.addEventListener("pause", () => {
        playBtn.style.display = "inline-flex";
        pauseBtn.style.display = "none";
    });

    // --- Button handlers ---
    playBtn.addEventListener("click", () => {
        audio.volume = 0;
        audio.play();
        fadeVolume(audio, 1);
    });
    pauseBtn.addEventListener("click", () => {
        fadeVolume(audio, 0, 200);
        setTimeout(() => audio.pause(), 210);
    });
    seekBar.addEventListener("input", () => {
        if (!isNaN(audio.duration)) {
            audio.currentTime = (seekBar.value / 100) * audio.duration;
        }
    });
    nextBtn.addEventListener("click", () => snapNext());
    prevBtn.addEventListener("click", () => snapPrevious());
    hookBtn.addEventListener("click", () => {
        hookIndex = (hookIndex + 1) % slideHooks.length;
        // Crossfade within same song to new hook
        fadeVolume(audio, 0, 120);
        setTimeout(() => {
            audio.currentTime = parseTime(slideHooks[hookIndex]);
            audio.play().catch(() => { });
            fadeVolume(audio, 1, 120);
        }, 140);
    });

    // --- Position off-screen initially ---
    el.style.transform = "translateY(100%)";
    carousel.appendChild(el);

    const slideObj = {
        el,
        audio,
        songId: song.id,
        song,
        hooks: slideHooks,
        hookIndex: 0
    };

    return slideObj;
}


// =============================================
//  CROSSFADE — SIMULTANEOUS (no gap)
//
//  Old: fade out → wait 100ms → play incoming → fade in (serial = gap)
//  New: play incoming at vol 0 → fade out + fade in AT SAME TIME
// =============================================

function performCrossfade(fromSlide, toSlide) {
    const fromAudio = fromSlide?.audio;
    const toAudio = toSlide.audio;

    // Incoming: volume 0, start playing immediately
    toAudio.volume = 0;
    toAudio.play().catch(() => { });

    // SIMULTANEOUS: both fades start at the same instant
    if (fromAudio) {
        fadeVolume(fromAudio, 0, CROSSFADE_MS);
        // Pause old audio only after its fade completes
        setTimeout(() => {
            fromAudio.pause();
        }, CROSSFADE_MS + 30);
    }
    fadeVolume(toAudio, 1, CROSSFADE_MS);
}


// =============================================
//  POSITION ALL SLIDES (relative to currentSlideIndex)
// =============================================

function positionSlides(animate) {
    slides.forEach((s, i) => {
        if (animate) {
            s.el.classList.remove("no-transition");
        } else {
            s.el.classList.add("no-transition");
        }
        s.el.style.transform = `translateY(${(i - currentSlideIndex) * 100}%)`;
    });
}

// During drag: move all slides by pixel offset
function positionSlidesDrag(dragPx) {
    const vh = window.innerHeight;
    slides.forEach((s, i) => {
        s.el.classList.add("no-transition");
        s.el.style.transform = `translateY(${(i - currentSlideIndex) * vh + dragPx}px)`;
    });
}

// Snap back to grid (when drag doesn't pass threshold)
function snapBackSlides() {
    slides.forEach((s, i) => {
        s.el.classList.remove("no-transition");
        s.el.style.transform = `translateY(${(i - currentSlideIndex) * 100}%)`;
    });
}


// =============================================
//  NAVIGATE TO SLIDE (for existing slides)
// =============================================

function navigateTo(newIndex) {
    if (isTransitioning) return false;
    if (newIndex < 0 || newIndex >= slides.length) return false;
    if (newIndex === currentSlideIndex) return false;

    isTransitioning = true;

    const fromSlide = slides[currentSlideIndex];
    const toSlide = slides[newIndex];

    currentSlideIndex = newIndex;

    // CSS transition handles the visual slide
    positionSlides(true);

    // Audio crossfade (simultaneous, no gap)
    performCrossfade(fromSlide, toSlide);

    // Update gradient from new slide's cover
    const cover = toSlide.el.querySelector(".cover-img");
    if (cover.complete && cover.naturalWidth > 0) {
        setPremiumGradient(cover);
    } else {
        const self = toSlide;
        cover.addEventListener("load", () => {
            if (slides[currentSlideIndex] === self) {
                setPremiumGradient(cover);
            }
        }, { once: true });
    }

    // Media session
    updateMediaSession(toSlide.song);

    // Reset timing for action decision
    startTime = Date.now();

    setTimeout(() => {
        isTransitioning = false;
        prefetchAhead();  // keep buffer full after each navigation
    }, TRANSITION_MS + 30);

    return true;
}


// =============================================
//  CLEANUP OLD SLIDES (memory cap)
// =============================================

function cleanupOldSlides() {
    while (slides.length > MAX_SLIDES) {
        const removed = slides.shift();
        removed.audio.pause();
        removed.audio.removeAttribute("src");
        removed.audio.load(); // release buffer
        removed.el.remove();
        currentSlideIndex--;
    }
}


// =============================================
//  PREFETCH — keep PREFETCH_AHEAD slides ready
//  Uses action=prefetch so the backend does NOT
//  modify the user's taste vector for unseen songs.
// =============================================

let isPrefetching = false;

async function prefetchAhead() {
    if (isPrefetching) return;

    const ahead = slides.length - 1 - currentSlideIndex;
    const needed = PREFETCH_AHEAD - ahead;
    if (needed <= 0) return;

    isPrefetching = true;
    const lang = getBestLanguage() || "";

    for (let i = 0; i < needed; i++) {
        try {
            const res = await fetch(`/next_song?action=prefetch&preferred_lang=${lang}`);
            if (!res.ok) break;
            const song = await res.json();

            // Create slide silently (positioned off-screen)
            const slide = createSlide(song);
            slides.push(slide);
            cleanupOldSlides();

            markInCache(song.id);
            pushHistory(song.id);
        } catch (err) {
            console.error("Prefetch failed:", err);
            break;
        }
    }

    isPrefetching = false;
}


// =============================================
//  SNAP NEXT
//  Uses try/finally to guarantee isTransitioning
//  always resets even on network errors or retries.
// =============================================

function decideAction() {
    const seconds = (Date.now() - startTime) / 1000;
    if (seconds < 4) return "hard_skip";
    if (seconds < 12) return "skipped";
    return "liked";
}

async function snapNext() {
    if (isTransitioning) return;

    // ---- Existing forward slides: instant (no network) ----
    if (currentSlideIndex < slides.length - 1) {
        // Report the user's real action to the backend (fire-and-forget)
        // so the taste vector stays accurate even though the slide was prefetched.
        const action = decideAction();
        const lang = getBestLanguage() || "";
        const currentSongId = slides[currentSlideIndex]?.songId || "";
        fetch(`/report_action?action=${action}&song_id=${currentSongId}&preferred_lang=${lang}`)
            .catch(() => {});

        if (action === "liked") updateLangScore(slides[currentSlideIndex]?.song?.language || "unknown", +1);
        if (action === "skipped" || action === "hard_skip") updateLangScore(slides[currentSlideIndex]?.song?.language || "unknown", -1);

        navigateTo(currentSlideIndex + 1);
        return;
    }

    // ---- Fetch new song from backend ----
    isTransitioning = true;
    const action = decideAction();
    const lang = getBestLanguage() || "";
    let navigated = false;

    try {
        showLoader();

        const res = await fetch(`/next_song?action=${action}&preferred_lang=${lang}`);
        if (!res.ok) return;
        const song = await res.json();

        let finalSong = song;

        // Skip already-cached songs (with retry limit)
        if (isInCache(song.id)) {
            console.warn("Cached song, retrying...");
            for (let i = 0; i < MAX_RETRY; i++) {
                const r2 = await fetch(`/next_song?action=skipped&preferred_lang=${lang}`);
                if (!r2.ok) break;
                const s2 = await r2.json();
                if (!isInCache(s2.id)) {
                    finalSong = s2;
                    break;
                }
            }
        }

        finishSnapNext(finalSong, action);
        navigated = true;

    } catch (err) {
        console.error("Failed to load next song:", err);
    } finally {
        hideLoader();
        if (!navigated) {
            isTransitioning = false;
        }
    }
}

function finishSnapNext(song, action) {
    const slide = createSlide(song);
    slides.push(slide);
    cleanupOldSlides();

    // History & cache
    markInCache(song.id);
    pushHistory(song.id);
    if (action === "liked") updateLangScore(song.language || "unknown", +1);
    if (action === "skipped" || action === "hard_skip") updateLangScore(song.language || "unknown", -1);

    // Navigate to new slide
    isTransitioning = false;
    navigateTo(slides.length - 1);
    // navigateTo triggers prefetchAhead via its setTimeout
}


// =============================================
//  SNAP PREVIOUS (instant — slide already exists)
// =============================================

function snapPrevious() {
    if (isTransitioning) return;
    if (currentSlideIndex <= 0) return;
    navigateTo(currentSlideIndex - 1);
}


// =============================================
//  FIRST SONG LOAD (no transition, direct)
// =============================================

async function loadFirstSong() {
    const lang = getBestLanguage() || "";

    try {
        const res = await fetch(`/next_song?action=skip&preferred_lang=${lang}`);
        if (!res.ok) return;
        const song = await res.json();

        const slide = createSlide(song);
        slides.push(slide);
        currentSlideIndex = 0;

        // Position directly — no animation for first song
        slide.el.classList.add("no-transition");
        slide.el.style.transform = "translateY(0)";

        // Remove no-transition after paint
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                slide.el.classList.remove("no-transition");
            });
        });

        // Play first song with gentle fade-in
        const startPlayback = () => {
            slide.audio.currentTime = parseTime(slide.hooks[0]);
            slide.audio.volume = 0;
            slide.audio.play().catch(() => { });
            fadeVolume(slide.audio, 1, 500);
        };

        if (slide.audio.readyState >= 1) {
            startPlayback();
        } else {
            slide.audio.addEventListener("loadedmetadata", startPlayback, { once: true });
        }

        // History
        markInCache(song.id);
        pushHistory(song.id);

        // Media session + gradient
        updateMediaSession(song);
        const cover = slide.el.querySelector(".cover-img");
        cover.addEventListener("load", () => {
            if (currentSlideIndex === 0) setPremiumGradient(cover);
        }, { once: true });

        startTime = Date.now();

        // Prefetch next 2 songs in background
        prefetchAhead();

    } catch (err) {
        console.error("Failed to load first song:", err);
    }
}


// =============================================
//  SWIPE / TOUCH / WHEEL EVENTS
//
//  During drag: all slides move with the finger
//  Adjacent slides peek from the edges (like YouTube Shorts)
// =============================================

// --- WHEEL ---
document.addEventListener("wheel", e => {
    if (isTransitioning) return;

    offsetY -= e.deltaY * 0.5;
    const threshold = window.innerHeight * 0.25;

    // Exceeded threshold → navigate
    if (offsetY < -threshold) {
        offsetY = 0;
        snapBackSlides();
        snapNext();
        return;
    }
    if (offsetY > threshold) {
        offsetY = 0;
        snapBackSlides();
        snapPrevious();
        return;
    }

    // Visual drag feedback (all slides move)
    positionSlidesDrag(offsetY);
});

// Reset wheel drag when scrolling stops
document.addEventListener("wheel", (() => {
    let timeout;
    return () => {
        clearTimeout(timeout);
        timeout = setTimeout(() => {
            if (!isTransitioning && offsetY !== 0) {
                offsetY = 0;
                snapBackSlides();
            }
        }, 150);
    };
})());

// --- TOUCH (passive listeners for scroll performance) ---
document.addEventListener("touchstart", e => {
    if (isTransitioning) return;
    startY = e.touches[0].clientY;
}, { passive: true });

document.addEventListener("touchmove", e => {
    if (isTransitioning) return;
    offsetY = e.touches[0].clientY - startY;
    positionSlidesDrag(offsetY);
}, { passive: true });

document.addEventListener("touchend", () => {
    if (isTransitioning) return;

    const threshold = window.innerHeight * 0.25;

    // Swipe up → next
    if (offsetY < -threshold) {
        offsetY = 0;
        snapNext();
    }
    // Swipe down → previous
    else if (offsetY > threshold) {
        offsetY = 0;
        snapPrevious();
    }
    // Snap back
    else {
        offsetY = 0;
        snapBackSlides();
    }
}, { passive: true });


// =============================================
//  INIT
// =============================================

checkFirstTime();