import os
import re
import tempfile
import shutil
import sqlite3
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp

APP_NAME = "Mas Ibram Downloader Backend"
VERSION = "6.0.0"
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "admin123")
MUSIC_DB = Path(os.getenv("MUSIC_DB_PATH", "/data/mas_ibram_music.db"))
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/mas-ibram-downloads"))
MUSIC_DB.parent.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=APP_NAME, version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36"
SUPPORTED = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "twitter.com": "Twitter / X",
    "x.com": "Twitter / X",
    "spotify.com": "Spotify",
    "capcut.com": "CapCut",
    "capcut.net": "CapCut",
    "snackvideo.com": "Snack Video",
    "snackvideo.in": "Snack Video",
    "snackvideo.ltd": "Snack Video",
}


def music_init():
    with sqlite3.connect(MUSIC_DB) as con:
        con.execute("CREATE TABLE IF NOT EXISTS site_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def music_get():
    music_init()
    with sqlite3.connect(MUSIC_DB) as con:
        row = con.execute("SELECT value FROM site_config WHERE key='music_url'").fetchone()
    return row[0] if row else ""


music_init()


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(400, "URL tidak valid.")
    return url


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().lstrip("www.")


def platform_for(url: str):
    host = host_of(url)
    for domain, name in SUPPORTED.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE).strip()
    return name[:160] or "MasIbram_Media"


def resolve_redirect(url: str) -> str:
    """Follow Snack Video and other public short-link redirects."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"}, method="HEAD")
        with urllib.request.urlopen(req, timeout=12) as r:
            final = r.geturl()
            if final:
                return final
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"}, method="GET")
        with urllib.request.urlopen(req, timeout=15) as r:
            final = r.geturl()
            if final:
                return final
    except Exception:
        pass
    return url


def youtube_strategies():
    # These are public yt-dlp extractor clients. They do not bypass account
    # authentication, DRM, or private cookies. YouTube may still block a video.
    return [
        {"extractor_args": {"youtube": {"player_client": ["android_vr"]}}},
        {"extractor_args": {"youtube": {"player_client": ["web_safari"]}}},
        {"extractor_args": {"youtube": {"player_client": ["mweb"]}}},
        {"extractor_args": {"youtube": {"player_client": ["web_embedded"]}}},
        {"extractor_args": {"youtube": {"player_client": ["tv"]}}},
        {},
    ]


def common_opts():
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "http_headers": {
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
        },
    }


def blocked_reason(platform: str, message: str) -> str | None:
    m = (message or "").lower()
    if platform == "Spotify" and ("drm" in m or "protected" in m or "not supported" in m):
        return (
            "Spotify menolak pengambilan audio karena perlindungan DRM. "
            "Backend ini tidak membypass DRM. Gunakan fitur unduh resmi Spotify Premium."
        )
    if platform == "YouTube" and (
        "sign in to confirm" in m or "not a bot" in m or "cookies" in m or "authentication" in m
    ):
        return (
            "YouTube menolak permintaan server karena verifikasi anti-bot. "
            "Client publik sudah dicoba, tetapi video ini masih meminta verifikasi tambahan."
        )
    if platform == "Snack Video" and ("unsupported url" in m or "no suitable extractor" in m):
        return (
            "Snack Video belum dapat dibaca oleh extractor saat ini. "
            "Link pendek sudah dicoba diikuti, tetapi halaman publiknya tidak memberikan media yang dapat diekstrak."
        )
    return None


def ydl_extract(url: str, download: bool, output: Path | None = None, audio: bool = False, strategy: dict | None = None):
    opts = common_opts()
    opts["skip_download"] = not download
    if output is not None:
        opts["outtmpl"] = str(output.with_suffix(".%(ext)s"))
        if audio:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            opts["format"] = "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/best"
            opts["merge_output_format"] = "mp4"
    if strategy:
        opts.update(strategy)
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=download)


def extract_info_with_fallback(url: str):
    platform = platform_for(url)
    attempts = youtube_strategies() if platform == "YouTube" else [{}]
    errors = []
    for strategy in attempts:
        try:
            return ydl_extract(url, download=False, strategy=strategy)
        except Exception as exc:
            errors.append(str(exc))
    msg = errors[-1] if errors else "Gagal membaca media."
    friendly = blocked_reason(platform or "", msg)
    raise RuntimeError(friendly or msg[:1400])


def extract_download(url: str, audio: bool, output: Path):
    platform = platform_for(url)
    attempts = youtube_strategies() if platform == "YouTube" else [{}]
    errors = []
    for strategy in attempts:
        try:
            info = ydl_extract(url, download=True, output=output, audio=audio, strategy=strategy)
            return info.get("title") or "Mas Ibram Media"
        except Exception as exc:
            errors.append(str(exc))
    msg = errors[-1] if errors else "Ekstraksi media gagal."
    friendly = blocked_reason(platform or "", msg)
    raise RuntimeError(friendly or msg[:1400])


def find_output(stem: str, audio: bool):
    expected = ".mp3" if audio else ".mp4"
    exact = DOWNLOAD_DIR / (stem + expected)
    if exact.exists():
        return exact
    candidates = sorted(
        [p for p in DOWNLOAD_DIR.glob(stem + ".*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def cleanup_old_files(max_age_seconds: int = 1800):
    now = __import__("time").time()
    for p in DOWNLOAD_DIR.iterdir():
        try:
            if p.is_file() and now - p.stat().st_mtime > max_age_seconds:
                p.unlink(missing_ok=True)
        except Exception:
            pass


@app.get("/")
def root():
    return {
        "ok": True,
        "service": APP_NAME,
        "version": VERSION,
        "platforms": sorted(set(SUPPORTED.values())),
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "version": VERSION,
        "yt_dlp": yt_dlp.version.__version__,
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }


@app.get("/platforms")
def platforms():
    return {"ok": True, "platforms": sorted(set(SUPPORTED.values()))}


@app.get("/music")
def get_music():
    return {"ok": True, "music_url": music_get(), "loop": True}


@app.post("/music")
def set_music(payload: dict = Body(...)):
    key = str(payload.get("admin_key", ""))
    if key != ADMIN_API_KEY:
        raise HTTPException(403, "Akses admin ditolak.")
    url = str(payload.get("music_url", "")).strip()
    if url and not re.match(r"^https?://", url, re.I):
        raise HTTPException(400, "URL musik harus diawali http:// atau https://")
    if len(url) > 2000:
        raise HTTPException(400, "URL musik terlalu panjang.")
    with sqlite3.connect(MUSIC_DB) as con:
        con.execute(
            "INSERT INTO site_config(key,value) VALUES('music_url',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (url,),
        )
    return {"ok": True, "music_url": url, "loop": True}


@app.get("/info")
def info(url: str = Query(...)):
    original = validate_url(url)
    resolved = resolve_redirect(original)
    platform = platform_for(resolved)
    if not platform:
        # Try the original host if a redirect endpoint itself is not recognized.
        platform = platform_for(original)
    if not platform:
        raise HTTPException(400, "Platform belum didukung.")

    try:
        data = extract_info_with_fallback(resolved)
        return {
            "ok": True,
            "platform": platform,
            "input_url": original,
            "resolved_url": resolved,
            "title": data.get("title"),
            "uploader": data.get("uploader") or data.get("channel"),
            "duration": data.get("duration"),
            "thumbnail": data.get("thumbnail"),
            "webpage_url": data.get("webpage_url") or resolved,
        }
    except Exception as e:
        raise HTTPException(502, f"Gagal membaca media: {str(e)[:1200]}")


@app.get("/download")
def download(url: str = Query(...), media: str = Query("video")):
    if media not in ("video", "audio"):
        raise HTTPException(400, "media harus video atau audio.")

    original = validate_url(url)
    resolved = resolve_redirect(original)
    platform = platform_for(resolved) or platform_for(original)
    if not platform:
        raise HTTPException(400, "Platform belum didukung.")

    if platform == "Spotify":
        raise HTTPException(
            400,
            "Spotify menolak pengambilan audio karena perlindungan DRM. Backend ini tidak membypass DRM. Gunakan fitur unduh resmi Spotify Premium.",
        )

    cleanup_old_files()
    audio = media == "audio"
    token = next(tempfile._get_candidate_names())
    target = DOWNLOAD_DIR / f"masibram_{token}"

    try:
        title = extract_download(resolved, audio, target)
        path = find_output(target.stem, audio)
        if not path:
            raise RuntimeError("File hasil download tidak ditemukan.")
    except Exception as e:
        raise HTTPException(502, f"Downloader gagal [{platform}]: {str(e)[:1200]}")

    ext = ".mp3" if audio else ".mp4"
    filename = safe_name(title) + ext
    media_type = "audio/mpeg" if audio else "video/mp4"
    return FileResponse(path, media_type=media_type, filename=filename)
