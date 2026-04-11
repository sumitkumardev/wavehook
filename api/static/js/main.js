
window.addEventListener("load", () => {
    localStorage.removeItem("previous_history");
    localStorage.removeItem("forward_history");
});

let startTime = 0;
let scrolling = false;
let offsetY = 0;

/* ===== DUAL-CARD SYSTEM ===== */
const cardA = document.getElementById("card-a");
const cardB = document.getElementById("card-b");

let activeCard = cardA;   // currently visible
let incomingCard = cardB;  // off-screen, used for next transition

// Helper: get elements within a specific card
function getCardElements(card) {
    return {
        cover: card.querySelector(".cover-img"),
        title: card.querySelector(".song-title"),
        artist: card.querySelector(".song-artist"),
        audio: card.querySelector(".song-audio"),
        progressBar: card.querySelector(".song-progress"),
        seekBar: card.querySelector(".song-seek"),
        currentTimeEl: card.querySelector(".song-current-time"),
        durationEl: card.querySelector(".song-duration"),
        playBtn: card.querySelector(".play-btn"),
        pauseBtn: card.querySelector(".pause-btn"),
        nextBtn: card.querySelector(".next-btn"),
        prevBtn: card.querySelector(".prev-btn"),
    };
}

// Current active audio shortcut
function getActiveAudio() {
    return activeCard.querySelector(".song-audio");
}

const CACHE_KEY = "played_songs_cache";
const LANG_KEY = "language_score";
const LANG_INIT = "language_initialized";

/* ===== TRANSITION DURATION (ms) ===== */
const TRANSITION_MS = 450;
const CROSSFADE_MS = 300;

/* ---------- MEDIA SESSION ---------- */
function updateMediaSession(song) {
    if ("mediaSession" in navigator) {
        navigator.mediaSession.metadata = new MediaMetadata({
            title: decodeHTMLEntities(song.name),
            artist: song.language || "WaveHook",
            album: "WaveHook",
            artwork: [
                { src: song.image[2].url, sizes: "256x256", type: "image/png" }
            ]
        });

        navigator.mediaSession.setActionHandler("play", () => getActiveAudio().play());
        navigator.mediaSession.setActionHandler("pause", () => getActiveAudio().pause());
        navigator.mediaSession.setActionHandler("nexttrack", () => snapNext());
        navigator.mediaSession.setActionHandler("previoustrack", () => snapPrevious());

    }
}

/* ---------- POSITION STATE ---------- */
function updatePositionState() {
    const audio = getActiveAudio();
    if ("mediaSession" in navigator && !isNaN(audio.duration)) {
        navigator.mediaSession.setPositionState({
            duration: audio.duration,
            playbackRate: audio.playbackRate,
            position: audio.currentTime
        });
    }
}

/* ---------- DARK MULTI-COLOR GRADIENT ---------- */
function extractPalette(img) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    const w = img.naturalWidth;
    const h = img.naturalHeight;
    canvas.width = w;
    canvas.height = h;

    ctx.drawImage(img, 0, 0, w, h);
    const data = ctx.getImageData(0, 0, w, h).data;

    let colors = [];
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

        // make colors MUCH darker (dark mode)
        const dark = c => `rgb(${c[0] * 0.25}, ${c[1] * 0.25}, ${c[2] * 0.25})`;

        const c1 = dark(palette[0]);
        const c2 = dark(palette[1]);
        const c3 = dark(palette[2]);

        document.body.style.background =
            `linear-gradient(120deg, ${c1}, ${c2}, ${c3})`;
    } catch (e) {
        // CORS or empty image — ignore silently
    }
}

/* ---------- HOOK CONTROL ---------- */
let hooks = [];
let currentHookIndex = 0;

function parseTime(t) {
    if (!t) return 0;
    let [m, s] = t.split(":");
    return parseInt(m) * 60 + parseInt(s);
}

function extractHooks(song) {
    let list = [];
    if (song.hook?.primehook) list.push(song.hook.primehook);
    if (song.hook?.sechook) list.push(song.hook.sechook);
    if (song.hook?.subhook) list.push(song.hook.subhook);
    return list.length ? list : ["00:00"];
}

function crossfadeTo(seconds) {
    const audio = getActiveAudio();
    if (!audio) return;

    fadeVolume(audio, 0, 150); // fade out

    setTimeout(() => {
        // jump to hook
        if (audio.fastSeek) {
            audio.fastSeek(seconds);
        } else {
            audio.currentTime = seconds;
        }

        // force resume
        audio.play().catch(() => { });

        // fade back in
        fadeVolume(audio, 1, 150);
    }, 180);
}


function playNextHook() {
    currentHookIndex = (currentHookIndex + 1) % hooks.length;
    crossfadeTo(parseTime(hooks[currentHookIndex]));
}

/* ---------- LANGUAGE STORAGE ---------- */
function getLangScore() { return JSON.parse(localStorage.getItem(LANG_KEY) || "{}"); }
function saveLangScore(obj) { localStorage.setItem(LANG_KEY, JSON.stringify(obj)); }
function updateLangScore(lang, delta) {
    let s = getLangScore();
    if (!s[lang]) s[lang] = 5;
    s[lang] = Math.max(1, Math.min(10, s[lang] + delta));
    saveLangScore(s);
}
function getBestLanguage() {
    let s = getLangScore(), best = null, val = -1;
    for (let k in s) { if (s[k] > val) { val = s[k]; best = k; } }
    return best;
}
function saveLanguagePreference() {
    let checks = document.querySelectorAll("#langPanel input:checked");
    let scores = {}, selected = [...checks].map(c => c.value);

    if (selected.includes("all") || !selected.length) {
        saveLangScore({});
    } else {
        selected.forEach(l => scores[l] = 8);
        saveLangScore(scores);
    }

    document.getElementById("langPanel").style.display = "none";
    loadFirstSong();
}

function checkFirstTime() {
    document.getElementById("langPanel").style.display = "flex";
}

/* ---------- CACHE ---------- */
function getCache() { return JSON.parse(localStorage.getItem(CACHE_KEY) || "{}"); }
function saveCache(c) { localStorage.setItem(CACHE_KEY, JSON.stringify(c)); }
function isInCache(id) { return id in getCache(); }
function markInCache(id) { let c = getCache(); c[id] = Date.now(); saveCache(c); }

// HISTORY
const HISTORY_KEY = "played_history";

function getHistory() {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
}

function saveHistory(arr) {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(arr));
}

// previous key
const PREVIOUS_KEY = "previous_history";

function getPrevious() {
    return JSON.parse(localStorage.getItem(PREVIOUS_KEY) || "[]");
}

function savePrevious(arr) {
    localStorage.setItem(PREVIOUS_KEY, JSON.stringify(arr));
}


// forward HISTORY
const FORWARD_KEY = "forward_history";

function getForward() {
    return JSON.parse(localStorage.getItem(FORWARD_KEY) || "[]");
}

function saveForward(arr) {
    localStorage.setItem(FORWARD_KEY, JSON.stringify(arr));
}



/* ---------- FIX SONG &quot ---------- */

function decodeHTMLEntities(text) {
    const parser = new DOMParser();
    const decodedString = parser.parseFromString(`<!doctype html><body>${text}`, 'text/html').body.textContent;
    return decodedString;
}
/* ---------- MARQUEE TITLE ---------- */
function applyMarqueeToTitle(titleEl, text) {
    if (text.length <= 20) {
        titleEl.classList.remove("animate");
        titleEl.innerText = text;
        return;
    }

    const separator = "\u00A0\u00A0♪\u00A0\u00A0"; // space ♪ space (non-breaking)

    const repeated = text + separator;

    titleEl.innerHTML = `
    <span class="marquee-track">
      <span class="marquee-item">${repeated}</span>
      <span class="marquee-item">${repeated}</span>
    </span>
  `;

    titleEl.classList.add("animate");
}


/* =============================================
   FADE VOLUME UTILITY (per-audio element)
============================================= */
const fadeIntervals = new WeakMap();

function fadeVolume(audioEl, targetVolume, duration = 250) {
    if (!audioEl) return;

    // Clear any existing fade for this audio element
    const existing = fadeIntervals.get(audioEl);
    if (existing) clearInterval(existing);

    const steps = 20;
    const stepTime = duration / steps;
    let currentVolume = audioEl.volume;
    const step = (targetVolume - currentVolume) / steps;

    const interval = setInterval(() => {
        currentVolume += step;
        audioEl.volume = Math.min(Math.max(currentVolume, 0), 1);

        if (
            (step > 0 && audioEl.volume >= targetVolume) ||
            (step < 0 && audioEl.volume <= targetVolume) ||
            step === 0
        ) {
            clearInterval(interval);
            fadeIntervals.delete(audioEl);
            audioEl.volume = Math.min(Math.max(targetVolume, 0), 1);
        }
    }, stepTime);

    fadeIntervals.set(audioEl, interval);
}


/* =============================================
   POPULATE A CARD with song data
============================================= */
// Bug 18 fix: track a generation counter so stale cover.onload is ignored
let coverGeneration = 0;

function populateCard(card, song) {
    const els = getCardElements(card);

    // Title
    applyMarqueeToTitle(els.title, decodeHTMLEntities(song.name));

    // Artist
    const artists = song.artists?.primary?.map(a => decodeHTMLEntities(a.name)) || [];
    els.artist.innerText =
        artists.length > 2
            ? artists.slice(0, 2).join(", ") + " & more"
            : artists.join(", ") || "Unknown Artist";

    // Cover (Bug 18: use generation counter to ignore stale loads)
    const gen = ++coverGeneration;
    els.cover.src = song.image[2].url;
    els.cover.onload = () => {
        if (gen === coverGeneration) {
            setPremiumGradient(els.cover);
        }
    };

    // Audio
    els.audio.src = song.downloadUrl[4].url;

    // Hooks
    hooks = extractHooks(song);
    currentHookIndex = 0;

    // Reset progress UI
    els.progressBar.style.width = "0%";
    els.seekBar.value = 0;
    els.currentTimeEl.textContent = "0:00";
    els.durationEl.textContent = "0:00";

    // Button state
    els.playBtn.style.display = "inline-flex";
    els.pauseBtn.style.display = "none";

    // onloadedmetadata: seek to hook and play
    els.audio.onloadedmetadata = () => {
        els.audio.currentTime = parseTime(hooks[0]);
        els.audio.play().catch(() => { });

        const mins = Math.floor(els.audio.duration / 60);
        const secs = Math.floor(els.audio.duration % 60);
        els.durationEl.textContent = `${mins}:${secs < 10 ? "0" : ""}${secs}`;
    };

    updateMediaSession(song);
}


/* =============================================
   DUAL-CARD TRANSITION ENGINE
============================================= */

function swapCards() {
    const temp = activeCard;
    activeCard = incomingCard;
    incomingCard = temp;
}

// Slide the incoming card IN from below, active card OUT upward
function transitionNext(callback) {
    const outgoing = activeCard;
    const incoming = incomingCard;

    // Position incoming just below the screen
    incoming.className = "song-card";
    incoming.style.transform = "translateY(100%)";
    incoming.style.opacity = "0";

    // Force reflow so the starting position is applied
    incoming.offsetHeight;

    // Add transition classes
    outgoing.classList.add("slide-exit-up");
    incoming.classList.add("slide-enter-up");

    // Audio crossfade
    const outAudio = outgoing.querySelector(".song-audio");
    const inAudio = incoming.querySelector(".song-audio");

    fadeVolume(outAudio, 0, CROSSFADE_MS);

    // Slight delay before starting incoming audio
    setTimeout(() => {
        inAudio.volume = 0;
        inAudio.play().catch(() => { });
        fadeVolume(inAudio, 1, CROSSFADE_MS);
    }, 100);

    // After transition completes
    setTimeout(() => {
        // Stop old audio
        outAudio.pause();
        outAudio.currentTime = 0;

        // Reset classes
        outgoing.className = "song-card incoming-card";
        incoming.className = "song-card active-card";

        // Reset inline styles
        outgoing.style.transform = "";
        outgoing.style.opacity = "";
        incoming.style.transform = "";
        incoming.style.opacity = "";

        swapCards();
        rebindActiveCardEvents();

        if (callback) callback();
    }, TRANSITION_MS + 50);
}

// Slide the incoming card IN from above, active card OUT downward
function transitionPrevious(callback) {
    const outgoing = activeCard;
    const incoming = incomingCard;

    // Position incoming just above the screen
    incoming.className = "song-card";
    incoming.style.transform = "translateY(-100%)";
    incoming.style.opacity = "0";

    // Force reflow
    incoming.offsetHeight;

    // Add transition classes
    outgoing.classList.add("slide-exit-down");
    incoming.classList.add("slide-enter-down");

    // Audio crossfade
    const outAudio = outgoing.querySelector(".song-audio");
    const inAudio = incoming.querySelector(".song-audio");

    fadeVolume(outAudio, 0, CROSSFADE_MS);

    setTimeout(() => {
        inAudio.volume = 0;
        inAudio.play().catch(() => { });
        fadeVolume(inAudio, 1, CROSSFADE_MS);
    }, 100);

    // After transition completes
    setTimeout(() => {
        outAudio.pause();
        outAudio.currentTime = 0;

        outgoing.className = "song-card incoming-card";
        incoming.className = "song-card active-card";

        outgoing.style.transform = "";
        outgoing.style.opacity = "";
        incoming.style.transform = "";
        incoming.style.opacity = "";

        swapCards();
        rebindActiveCardEvents();

        if (callback) callback();
    }, TRANSITION_MS + 50);
}


/* =============================================
   LOAD SONG (fetches from backend, populates incoming card)
============================================= */
const MAX_RETRY = 3; // Bug 14: prevent infinite recursion

async function loadSong(action = "skip", retryCount = 0) {
    let lang = getBestLanguage() || "";

    try {
        const res = await fetch(`/next_song?action=${action}&preferred_lang=${lang}`);

        if (!res.ok) {
            console.error("Server error:", res.status);
            scrolling = false;
            return;
        }

        const song = await res.json();

        // Bug 14: recursion depth limit
        if (isInCache(song.id)) {
            console.warn("Cached song skipped:", song.id);
            if (retryCount >= MAX_RETRY) {
                console.warn("Max retry reached, playing cached song.");
            } else {
                return loadSong("skipped", retryCount + 1);
            }
        }

        // Populate the INCOMING card
        populateCard(incomingCard, song);

        if (action === "liked") updateLangScore(song.language || "unknown", +1);
        if (action === "skipped") updateLangScore(song.language || "unknown", -1);

        let history = getHistory();

        // block same-song repeat
        if (history.length === 0 || history[history.length - 1] !== song.id) {
            history.push(song.id);
            saveHistory(history);
        } else {
            console.warn("Duplicate song prevented:", song.id);
        }

        // forward history — Bug 16: call saveForward once instead of twice
        saveForward([]);
        let prev = getPrevious();

        // prevent duplicate push
        if (prev.length === 0 || prev[prev.length - 1] !== song.id) {
            prev.push(song.id);
            savePrevious(prev);
        }

        markInCache(song.id);
        startTime = Date.now();

    } catch (err) {
        // Bug 13: handle fetch errors
        console.error("Failed to load song:", err);
        scrolling = false;
    }
}


function loadSongFromObject(song) {
    populateCard(incomingCard, song);
    startTime = Date.now();
}


/* =============================================
   FIRST SONG LOAD (special: no transition)
============================================= */
async function loadFirstSong() {
    let lang = getBestLanguage() || "";

    try {
        const res = await fetch(`/next_song?action=skip&preferred_lang=${lang}`);
        if (!res.ok) return;
        const song = await res.json();

        // Populate the ACTIVE card directly (no transition needed)
        populateCard(activeCard, song);

        let history = getHistory();
        if (history.length === 0 || history[history.length - 1] !== song.id) {
            history.push(song.id);
            saveHistory(history);
        }

        saveForward([]);
        let prev = getPrevious();
        if (prev.length === 0 || prev[prev.length - 1] !== song.id) {
            prev.push(song.id);
            savePrevious(prev);
        }

        markInCache(song.id);
        startTime = Date.now();

        rebindActiveCardEvents();

    } catch (err) {
        console.error("Failed to load first song:", err);
    }
}


// History IDs
async function snapPrevious() {
    if (scrolling) return;
    scrolling = true;

    let prev = getPrevious();
    let forward = getForward();

    if (prev.length < 2) {
        scrolling = false;
        return;
    }

    // move current → forward
    const currentId = prev.pop();
    forward.push(currentId);
    saveForward(forward);
    savePrevious(prev);

    const prevId = prev[prev.length - 1];

    try {
        const res = await fetch(`/song_by_id?id=${prevId}`);
        if (!res.ok) {
            scrolling = false;
            return;
        }
        const song = await res.json();

        // Populate incoming card with previous song
        loadSongFromObject(song);

        // Transition: incoming slides from top, active slides down
        transitionPrevious(() => {
            scrolling = false;
        });

    } catch (err) {
        console.error("Failed to load previous song:", err);
        scrolling = false;
    }
}


/* ---------- SWIPE ---------- */
function decideAction() {
    const seconds = (Date.now() - startTime) / 1000;
    if (seconds < 4) return "hard_skip";
    if (seconds < 12) return "skipped";
    return "liked";
}



async function snapNext() {
    if (scrolling) return;
    scrolling = true;

    let forward = getForward();

    // if coming from previous → go forward first
    if (forward.length > 0) {
        const nextId = forward.pop();
        saveForward(forward);

        try {
            const res = await fetch(`/song_by_id?id=${nextId}`);
            if (!res.ok) {
                scrolling = false;
                return;
            }
            const song = await res.json();

            loadSongFromObject(song);

            // push back to previous
            let prev = getPrevious();
            if (prev.length === 0 || prev[prev.length - 1] !== nextId) {
                prev.push(nextId);
                savePrevious(prev);
            }

            transitionNext(() => {
                scrolling = false;
            });

        } catch (err) {
            console.error("Failed to load forward song:", err);
            scrolling = false;
        }

        return;
    }

    // normal behavior (fetch new song from backend)
    let action = decideAction();

    await loadSong(action);

    // Trigger transition
    transitionNext(() => {
        scrolling = false;
    });
}


/* =============================================
   SWIPE + WHEEL EVENTS
============================================= */

// Bug 15: handle scroll in both directions properly
document.addEventListener("wheel", e => {
    if (scrolling) return;

    offsetY -= e.deltaY * 0.5;

    // Scroll down → next song
    if (offsetY < -window.innerHeight * 0.25) {
        offsetY = 0;
        activeCard.style.transform = "";
        snapNext();
        return;
    }

    // Scroll up → previous song
    if (offsetY > window.innerHeight * 0.25) {
        offsetY = 0;
        activeCard.style.transform = "";
        snapPrevious();
        return;
    }

    // Visual drag feedback
    activeCard.classList.add("dragging");
    activeCard.style.transform = `translateY(${offsetY}px)`;
});

// Reset on scroll end (no threshold reached)
document.addEventListener("wheel", (() => {
    let timeout;
    return (e) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => {
            if (!scrolling && offsetY !== 0) {
                offsetY = 0;
                activeCard.classList.remove("dragging");
                activeCard.style.transition = "transform 0.2s ease-out";
                activeCard.style.transform = "translateY(0)";
                setTimeout(() => {
                    activeCard.style.transition = "";
                    activeCard.style.transform = "";
                }, 200);
            }
        }, 150);
    };
})());


let startY = 0;

// Touch events: operate on active card
document.addEventListener("touchstart", e => {
    if (scrolling) return;
    startY = e.touches[0].clientY;
});

document.addEventListener("touchmove", e => {
    if (scrolling) return;
    let moveY = e.touches[0].clientY;
    offsetY = moveY - startY;
    activeCard.classList.add("dragging");
    activeCard.style.transform = `translateY(${offsetY}px)`;
});

document.addEventListener("touchend", () => {
    if (scrolling) return;

    // Swipe up → next
    if (offsetY < -window.innerHeight * 0.25) {
        offsetY = 0;
        activeCard.classList.remove("dragging");
        snapNext();
    }
    // Swipe down → previous
    else if (offsetY > window.innerHeight * 0.25) {
        offsetY = 0;
        activeCard.classList.remove("dragging");
        snapPrevious();
    }
    // Snap back
    else {
        activeCard.classList.remove("dragging");
        activeCard.style.transition = "transform 0.2s ease-out";
        activeCard.style.transform = "translateY(0)";
        setTimeout(() => {
            activeCard.style.transition = "";
            activeCard.style.transform = "";
        }, 200);
        offsetY = 0;
    }
});

checkFirstTime();


/* =============================================
   BIND EVENTS TO ACTIVE CARD
   Re-called after every card swap
============================================= */
function rebindActiveCardEvents() {
    const els = getCardElements(activeCard);
    const audio = els.audio;

    // Play/Pause buttons
    els.playBtn.onclick = () => {
        audio.volume = 0;
        audio.play();
        fadeVolume(audio, 1);
    };

    els.pauseBtn.onclick = () => {
        fadeVolume(audio, 0, 250);
        // Pause after fade completes (Bug 17 fix: no feedback loop)
        setTimeout(() => {
            audio.pause();
        }, 260);
    };

    // Bug 17 fix: audio state UI sync WITHOUT calling fadeVolume (avoids feedback loop)
    audio.onplay = () => {
        els.playBtn.style.display = "none";
        els.pauseBtn.style.display = "inline-flex";
    };

    audio.onpause = () => {
        els.playBtn.style.display = "inline-flex";
        els.pauseBtn.style.display = "none";
    };

    // Seek bar
    els.seekBar.oninput = () => {
        if (!isNaN(audio.duration)) {
            audio.currentTime = (els.seekBar.value / 100) * audio.duration;
        }
    };

    els.seekBar.onchange = () => {
        if (!audio.paused) audio.play();
    };

    // Song ended → auto next
    audio.onended = () => {
        snapNext();
    };

    // Time update + progress
    audio.ontimeupdate = () => {
        if (!audio.duration) return;

        const currentMins = Math.floor(audio.currentTime / 60);
        const currentSecs = Math.floor(audio.currentTime % 60);
        els.currentTimeEl.textContent =
            `${currentMins}:${currentSecs < 10 ? "0" : ""}${currentSecs}`;

        const progress = audio.currentTime / audio.duration;
        els.progressBar.style.width = `${progress * 100}%`;
        els.seekBar.value = progress * 100;

        // Update media session position state
        updatePositionState();
    };

    // Next / Previous buttons
    els.nextBtn.onclick = snapNext;
    els.prevBtn.onclick = snapPrevious;
}

// Initialize: bind events to the first active card
rebindActiveCardEvents();