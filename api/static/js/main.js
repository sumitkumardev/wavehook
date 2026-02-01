
window.addEventListener("load", () => {
    localStorage.removeItem("previous_history");
    localStorage.removeItem("forward_history");
});

let startTime = 0;
let scrolling = false;
let offsetY = 0;

const card = document.getElementById("card");
const audio = document.getElementById("player");

const CACHE_KEY = "played_songs_cache";
const LANG_KEY = "language_score";
const LANG_INIT = "language_initialized";

/* ---------- MEDIA SESSION ---------- */
function updateMediaSession(song) {
    if ("mediaSession" in navigator) {
        navigator.mediaSession.metadata = new MediaMetadata({
            title: song.name,
            artist: song.language || "WaveHook",
            album: "WaveHook",
            artwork: [
                { src: song.image[2].url, sizes: "256x256", type: "image/png" }
            ]
        });

        navigator.mediaSession.setActionHandler("play", () => audio.play());
        navigator.mediaSession.setActionHandler("pause", () => audio.pause());
        navigator.mediaSession.setActionHandler("nexttrack", () => snapNext());
        navigator.mediaSession.setActionHandler("previoustrack", () => snapPrevious());

    }
}

/* ---------- POSITION STATE ---------- */
function updatePositionState() {
    if ("mediaSession" in navigator && !isNaN(audio.duration)) {
        navigator.mediaSession.setPositionState({
            duration: audio.duration,
            playbackRate: audio.playbackRate,
            position: audio.currentTime
        });
    }
}
audio.addEventListener("timeupdate", updatePositionState);

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
    const palette = extractPalette(img);

    // make colors MUCH darker (dark mode)
    const dark = c => `rgb(${c[0] * 0.25}, ${c[1] * 0.25}, ${c[2] * 0.25})`;

    const c1 = dark(palette[0]);
    const c2 = dark(palette[1]);
    const c3 = dark(palette[2]);

    document.body.style.background =
        `linear-gradient(120deg, ${c1}, ${c2}, ${c3})`;
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
    if (!audio) return;

    const wasPlaying = !audio.paused; // remember state

    fadeVolume(0, 150); // fade out

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
        fadeVolume(1, 150);
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
    loadSong();
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
function applyMarqueeToTitle(text) {
    const title = document.getElementById("title");

    if (text.length <= 20) {
        title.classList.remove("animate");
        title.innerText = text;
        return;
    }

    const separator = "\u00A0\u00A0♪\u00A0\u00A0"; // space ♪ space (non-breaking)

    const repeated = text + separator;

    title.innerHTML = `
    <span class="marquee-track">
      <span class="marquee-item">${repeated}</span>
      <span class="marquee-item">${repeated}</span>
    </span>
  `;

    title.classList.add("animate");
}


/* ---------- LOAD SONG ---------- */
async function loadSong(action = "skip") {
    let lang = getBestLanguage() || "";
    const res = await fetch(`/next_song?action=${action}&preferred_lang=${lang}`);
    const song = await res.json();

    // if (isInCache(song.id)) return loadSong("liked");
    if (isInCache(song.id)) {
        console.warn("Cached song skipped:", song.id);
        return loadSong("skipped");
    }

    // document.getElementById("title").innerText = decodeHTMLEntities(song.name);
    applyMarqueeToTitle(decodeHTMLEntities(song.name));
    // document.getElementById("artist").innerText = song.language;
    const artists = song.artists?.primary?.map(a => decodeHTMLEntities(a.name)) || [];
    document.getElementById("artist").innerText =
        artists.length > 2
            ? artists.slice(0, 2).join(", ") + " & more"
            : artists.join(", ") || "Unknown Artist";


    // applyMarqueeToTitle();

    const cover = document.getElementById("cover");
    cover.crossOrigin = "anonymous";
    cover.src = song.image[2].url;
    cover.onload = () => setPremiumGradient(cover);

    updateMediaSession(song);

    audio.src = song.downloadUrl[4].url;
    hooks = extractHooks(song);
    currentHookIndex = 0;

    audio.onloadedmetadata = () => {
        audio.currentTime = parseTime(hooks[0]);
        audio.play();
    };

    if (action === "liked") updateLangScore(song.language || "unknown", +1);
    if (action === "skipped") updateLangScore(song.language || "unknown", -1);

    // markInCache(song.id);
    // startTime = Date.now();
    let history = getHistory();

    // block same-song repeat
    if (history.length === 0 || history[history.length - 1] !== song.id) {
        history.push(song.id);
        saveHistory(history);
    } else {
        console.warn("Duplicate song prevented:", song.id);
    }

    // forward history
    saveForward([]);
    let prev = getPrevious();

    // prevent duplicate push
    if (prev.length === 0 || prev[prev.length - 1] !== song.id) {
        prev.push(song.id);
        savePrevious(prev);
    }

    // new song from backend → clear forward stack
    saveForward([]);


    markInCache(song.id);
    startTime = Date.now();

}


function loadSongFromObject(song) {
    // title
    applyMarqueeToTitle(decodeHTMLEntities(song.name));

    // artist
    const artists = song.artists?.primary?.map(a => a.name) || [];
    document.getElementById("artist").innerText =
        artists.length > 2
            ? artists.slice(0, 2).join(", ") + " & more"
            : artists.join(", ") || "Unknown Artist";

    // cover
    const cover = document.getElementById("cover");
    cover.crossOrigin = "anonymous";
    cover.src = song.image[2].url;
    cover.onload = () => setPremiumGradient(cover);

    // media session
    updateMediaSession(song);

    // audio
    audio.src = song.downloadUrl[4].url;

    // hooks
    hooks = extractHooks(song);
    currentHookIndex = 0;

    audio.onloadedmetadata = () => {
        audio.currentTime = parseTime(hooks[0]);
        audio.play();
    };

    startTime = Date.now();
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

    card.style.transform = "translateY(100%)";

    setTimeout(async () => {
        const res = await fetch(`/song_by_id?id=${prevId}`);
        const song = await res.json();

        loadSongFromObject(song);

        card.style.transition = "none";
        card.style.transform = "translateY(-100%)";

        requestAnimationFrame(() => {
            card.style.transition = "transform 0.35s ease-out";
            card.style.transform = "translateY(0)";
            scrolling = false;
        });
    }, 350);
}


/* ---------- SWIPE ---------- */
function decideAction() {
    return (Date.now() - startTime) / 1000 > 12 ? "liked" : "skipped";
}
async function snapNext() {
    if (scrolling) return;
    scrolling = true;

    let forward = getForward();

    // if coming from previous → go forward first
    if (forward.length > 0) {
        const nextId = forward.pop();
        saveForward(forward);

        card.style.transform = "translateY(-100%)";

        setTimeout(async () => {
            const res = await fetch(`/song_by_id?id=${nextId}`);
            const song = await res.json();

            loadSongFromObject(song);

            card.style.transition = "none";
            card.style.transform = "translateY(100%)";

            requestAnimationFrame(() => {
                card.style.transition = "transform 0.35s ease-out";
                card.style.transform = "translateY(0)";
                scrolling = false;
            });
        }, 350);

        return;
    }

    // normal behavior (your old algo)
    let action = decideAction();
    card.style.transform = "translateY(-100%)";

    setTimeout(async () => {
        await loadSong(action);

        card.style.transition = "none";
        card.style.transform = "translateY(100%)";

        requestAnimationFrame(() => {
            card.style.transition = "transform 0.35s ease-out";
            card.style.transform = "translateY(0)";
            scrolling = false;
        });
    }, 350);
}

document.addEventListener("wheel", e => {
    if (scrolling) return;
    offsetY -= e.deltaY * 0.5;
    card.style.transform = `translateY(${offsetY}px)`;
    if (offsetY < -window.innerHeight * 0.25) { offsetY = 0; snapNext(); }
}); let startY = 0;
card.addEventListener("touchstart", e => {
    startY = e.touches[0].clientY;
});
card.addEventListener("touchmove", e => {
    let moveY = e.touches[0].clientY;
    offsetY = moveY - startY;
    card.style.transition = "none";
    card.style.transform = `translateY(${offsetY}px)`;
});
card.addEventListener("touchend", () => {
    if (offsetY < -window.innerHeight * 0.25) { offsetY = 0; snapNext(); } else {
        card.style.transition = "transform 0.2s ease-out"; card.style.transform = "translateY(0)"; offsetY = 0;
    }
});
checkFirstTime();






// play pause func



const playButton = document.getElementById("play");
const pauseButton = document.getElementById("pause");

const progressBar = document.getElementById("progress-bar");
const seekBar = document.getElementById("seek");

const totalDuration = document.getElementById("duration");
const currentTimeEl = document.getElementById("current-time");

/* =========================
   FADE CONTROL (SAFE)
========================= */
let fadeInterval = null;

function fadeVolume(targetVolume, duration = 250) {
    if (!audio) return;

    if (fadeInterval) clearInterval(fadeInterval);

    const steps = 20;
    const stepTime = duration / steps;
    let currentVolume = audio.volume;
    const step = (targetVolume - currentVolume) / steps;

    fadeInterval = setInterval(() => {
        currentVolume += step;
        audio.volume = Math.min(Math.max(currentVolume, 0), 1);

        if (
            (step > 0 && audio.volume >= targetVolume) ||
            (step < 0 && audio.volume <= targetVolume)
        ) {
            clearInterval(fadeInterval);
            fadeInterval = null;
            audio.volume = targetVolume;

            if (targetVolume === 0) audio.pause();
        }
    }, stepTime);
}

/* =========================
   BUTTON ACTIONS
========================= */
playButton.addEventListener("click", () => {
    audio.volume = 0;
    audio.play();
    fadeVolume(1);
});

pauseButton.addEventListener("click", () => {
    fadeVolume(0);
});


/* =========================
   AUDIO STATE → UI SYNC
   (LOCKSCREEN / NOTIFICATION SAFE)
========================= */
audio.addEventListener("play", () => {
    playButton.style.display = "none";
    pauseButton.style.display = "inline-flex";
    fadeVolume(1);
});

audio.addEventListener("pause", () => {
    playButton.style.display = "inline-flex";
    pauseButton.style.display = "none";
    fadeVolume(0);
});

/* =========================
   SEEK BAR (MOBILE SAFE)
========================= */
seekBar.addEventListener("input", () => {
    if (!isNaN(audio.duration)) {
        audio.currentTime = (seekBar.value / 100) * audio.duration;
    }
});

seekBar.addEventListener("change", () => {
    if (!audio.paused) audio.play();
});
audio.addEventListener("ended", () => {
    snapNext();
});

/* =========================
   METADATA LOADED
========================= */
audio.addEventListener("loadedmetadata", () => {
    const mins = Math.floor(audio.duration / 60);
    const secs = Math.floor(audio.duration % 60);
    totalDuration.textContent = `${mins}:${secs < 10 ? "0" : ""}${secs}`;
});

/* =========================
   TIME UPDATE + PROGRESS
========================= */
audio.addEventListener("timeupdate", () => {
    if (!audio.duration) return;

    const currentMins = Math.floor(audio.currentTime / 60);
    const currentSecs = Math.floor(audio.currentTime % 60);
    currentTimeEl.textContent =
        `${currentMins}:${currentSecs < 10 ? "0" : ""}${currentSecs}`;

    const progress = audio.currentTime / audio.duration;
    progressBar.style.width = `${progress * 100}%`;
    seekBar.value = progress * 100;
});
document.getElementById("next").addEventListener("click", snapNext);
document.getElementById("previous").addEventListener("click", snapPrevious);