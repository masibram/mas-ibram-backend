import os
import re
import sqlite3
import tempfile
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp

APP_NAME = "Mas Ibram Downloader Backend"
VERSION = "8.0.0"
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/mas-ibram-downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
MUSIC_DB_PATH = Path(os.getenv("MUSIC_DB_PATH", "/data/mas_ibram_music.db"))
MUSIC_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "admin123")

app = FastAPI(title=APP_NAME, version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED = {
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook", "fb.watch": "Facebook",
    "twitter.com": "Twitter / X", "x.com": "Twitter / X",
    "spotify.com": "Spotify",
    "capcut.com": "CapCut", "capcut.net": "CapCut",
    "snackvideo.com": "Snack Video", "snackvideo.in": "Snack Video", "snackvideo.ltd": "Snack Video",
    # New platforms. Domain aliases are intentionally explicit; extractor
    # availability still depends on the actual URL and provider access rules.
    "freereels.com": "FreeReels Drama", "freereels.net": "FreeReels Drama", "freereels.app": "FreeReels Drama",
    "melolo.com": "Melolo TV", "melolo.tv": "Melolo TV", "melolo.app": "Melolo TV",
    "pinedrama.com": "PineDrama", "pinedrama.app": "PineDrama", "pinedrama.net": "PineDrama",
    "terabox.com": "TeraBox", "teraboxapp.com": "TeraBox", "terabox.app": "TeraBox",
    "1024tera.com": "TeraBox", "4funbox.com": "TeraBox",
}


def db_init():
    with sqlite3.connect(MUSIC_DB_PATH) as con:
        con.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.commit()


def get_music():
    db_init()
    with sqlite3.connect(MUSIC_DB_PATH) as con:
        row = con.execute("SELECT value FROM config WHERE key='music_url'").fetchone()
    return row[0] if row else ""


def set_music(url: str):
    db_init()
    with sqlite3.connect(MUSIC_DB_PATH) as con:
        con.execute("INSERT INTO config(key,value) VALUES('music_url',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (url,))
        con.commit()


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(400, "URL tidak valid.")
    return url


def platform_for(url: str):
    host = (urlparse(url).hostname or "").lower().lstrip("www.")
    for domain, name in SUPPORTED.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE).strip()
    return name[:160] or "MasIbram_Media"


def common_opts():
    return {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "file_access_retries": 3,
        "socket_timeout": 25,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }


def youtube_strategies():
    # Public clients only. YouTube can still require a PO token/cookie for
    # some videos; no personal cookies are collected by this backend.
    clients = [
        ["android_vr"],
        ["web_safari"],
        ["mweb"],
        ["web_embedded"],
        ["android"],
        ["ios"],
        [],
    ]
    return [{"extractor_args": {"youtube": {"player_client": c}}} if c else {} for c in clients]


def platform_strategies(platform: str):
    if platform == "YouTube":
        return youtube_strategies()
    if platform == "Instagram":
        return [
            {"http_headers": {"User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36", "Referer": "https://www.instagram.com/"}},
            {"http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36", "Referer": "https://www.instagram.com/"}},
            {},
        ]
    if platform == "TikTok":
        return [
            {"http_headers": {"User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36", "Referer": "https://www.tiktok.com/"}},
            {"http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36", "Referer": "https://www.tiktok.com/"}},
            {},
        ]
    return [{}]


def blocked_reason(platform: str, message: str):
    m = message.lower()
    if platform == "Spotify":
        return "Downloader Spotify dalam masa perbaikan dan tidak bisa di gunakan untuk saat ini."
    if platform == "YouTube" and any(x in m for x in ("sign in to confirm", "confirm you're not a bot", "not a bot", "po token", "bot detection")):
        return "YouTube menolak permintaan server karena verifikasi anti-bot. Video ini memerlukan verifikasi tambahan dari YouTube."
    if platform == "Instagram" and any(x in m for x in ("empty media response", "login required", "challenge", "checkpoint")):
        return "Instagram tidak memberikan media kepada server. Pastikan posting bersifat publik dan dapat dibuka tanpa login."
    if platform == "TikTok" and any(x in m for x in ("login", "captcha", "challenge", "blocked", "access denied")):
        return "TikTok menolak permintaan server. Coba tautan publik TikTok yang dapat dibuka tanpa login."
    if "drm" in m or "protected" in m or "widevine" in m:
        return f"{platform} menandai media sebagai terlindungi/DRM dan tidak dapat diambil tanpa membypass perlindungan."
    if platform in ("FreeReels Drama", "Melolo TV", "PineDrama") and any(
        x in m for x in ("unsupported url", "no suitable extractor", "unable to download webpage", "login required", "sign in")
    ):
        return (
            f"{platform} belum dapat diekstrak oleh yt-dlp untuk tautan ini. "
            "Aplikasi mungkin memakai API aplikasi, login, atau DRM yang tidak didukung. "
            "Gunakan tautan web publik yang resmi jika tersedia."
        )
    if platform == "TeraBox" and any(x in m for x in ("unsupported url", "no suitable extractor")):
        return (
            "Tautan TeraBox ini tidak dikenali oleh versi yt-dlp yang terpasang. "
            "Coba tautan berbagi publik asli dari TeraBox; tautan yang memerlukan login atau kode akses mungkin tidak didukung."
        )
    return None


def base_opts(audio: bool, output: Path):
    opts = common_opts()
    opts["outtmpl"] = str(output.with_suffix(".%(ext)s"))
    if audio:
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        })
    else:
        opts.update({
            "format": "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/best",
            "merge_output_format": "mp4",
        })
    return opts


def make_opts(url: str, audio: bool, output: Path, strategy=None):
    opts = base_opts(audio, output)
    if strategy:
        opts.update(strategy)
    return opts


def extract_download(url: str, audio: bool, output: Path):
    platform = platform_for(url)
    errors = []
    for strategy in platform_strategies(platform):
        try:
            with yt_dlp.YoutubeDL(make_opts(url, audio, output, strategy)) as ydl:
                info = ydl.extract_info(url, download=True)
                return info.get("title") or "Mas Ibram Media"
        except Exception as exc:
            errors.append(str(exc))
            # remove partial files before trying the next extractor strategy
            for p in DOWNLOAD_DIR.glob(output.stem + ".*"):
                try: p.unlink()
                except Exception: pass
    message = errors[-1] if errors else "Ekstraksi media gagal."
    friendly = blocked_reason(platform, message)
    raise RuntimeError(friendly or message[:1400])


def find_output(stem: str, audio: bool):
    expected = ".mp3" if audio else ".mp4"
    exact = DOWNLOAD_DIR / (stem + expected)
    if exact.exists(): return exact
    candidates = sorted([p for p in DOWNLOAD_DIR.glob(stem + ".*") if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def cleanup_old_files(max_age_seconds=1800):
    now = time.time()
    for p in DOWNLOAD_DIR.iterdir():
        try:
            if p.is_file() and now - p.stat().st_mtime > max_age_seconds:
                p.unlink(missing_ok=True)
        except Exception:
            pass


@app.on_event("startup")
def startup():
    db_init()


@app.get("/")
def root():
    return {"ok": True, "service": APP_NAME, "version": VERSION, "platforms": sorted(set(SUPPORTED.values()))}


@app.get("/health")
def health():
    return {"ok": True, "version": VERSION, "yt_dlp": yt_dlp.version.__version__, "ffmpeg": bool(shutil.which("ffmpeg")), "music_config": True}


@app.get("/platforms")
def platforms():
    return {"ok": True, "platforms": sorted(set(SUPPORTED.values()))}


@app.get("/music")
def music_get():
    return {"ok": True, "music_url": get_music()}


@app.post("/music")
def music_set(payload: dict):
    if payload.get("admin_key") != ADMIN_API_KEY:
        raise HTTPException(403, "Admin key salah.")
    url = str(payload.get("music_url") or "").strip()
    set_music(url)
    return {"ok": True, "music_url": url}


@app.get("/info")
def info(url: str = Query(...)):
    url = validate_url(url)
    platform = platform_for(url)
    if not platform:
        raise HTTPException(400, "Platform belum didukung.")
    if platform == "Spotify":
        raise HTTPException(503, "Downloader Spotify dalam masa perbaikan dan tidak bisa di gunakan untuk saat ini.")
    errors = []
    for strategy in platform_strategies(platform):
        try:
            opts = common_opts()
            opts.update({"skip_download": True})
            opts.update(strategy)
            with yt_dlp.YoutubeDL(opts) as ydl:
                data = ydl.extract_info(url, download=False)
            return {"ok": True, "platform": platform, "title": data.get("title"), "uploader": data.get("uploader"), "duration": data.get("duration"), "thumbnail": data.get("thumbnail"), "webpage_url": data.get("webpage_url") or url}
        except Exception as exc:
            errors.append(str(exc))
    message = errors[-1] if errors else "Gagal membaca media."
    friendly = blocked_reason(platform, message)
    raise HTTPException(502, f"Gagal membaca media: {(friendly or message)[:1200]}")


@app.get("/download")
def download(url: str = Query(...), media: str = Query("video")):
    if media not in ("video", "audio"):
        raise HTTPException(400, "media harus video atau audio.")
    url = validate_url(url)
    platform = platform_for(url)
    if not platform:
        raise HTTPException(400, "Platform belum didukung.")
    if platform == "Spotify":
        raise HTTPException(503, "Downloader Spotify dalam masa perbaikan dan tidak bisa di gunakan untuk saat ini.")
    cleanup_old_files()
    audio = media == "audio"
    token = next(tempfile._get_candidate_names())
    target = DOWNLOAD_DIR / f"masibram_{token}"
    try:
        title = extract_download(url, audio, target)
        path = find_output(target.stem, audio)
        if not path:
            raise RuntimeError("File hasil download tidak ditemukan.")
    except Exception as e:
        raise HTTPException(502, f"Downloader gagal [{platform}]: {str(e)[:1200]}")
    ext = ".mp3" if audio else ".mp4"
    return FileResponse(path, media_type="audio/mpeg" if audio else "video/mp4", filename=safe_name(title) + ext)
