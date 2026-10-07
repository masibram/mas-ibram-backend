import os
import re
import tempfile
import shutil
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp

APP_NAME = "Mas Ibram Downloader Backend"
VERSION = "4.0.0"
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/mas-ibram-downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=APP_NAME, version=VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


def youtube_strategies():
    # Try public extractor clients in a conservative order. YouTube may still
    # require a valid browser session/PO token depending on its current
    # anti-bot policy; this backend does not collect personal cookies.
    return [
        {"extractor_args": {"youtube": {"player_client": ["android_vr"]}}},
        {"extractor_args": {"youtube": {"player_client": ["web_safari"]}}},
        {"extractor_args": {"youtube": {"player_client": ["mweb"]}}},
        {"extractor_args": {"youtube": {"player_client": ["web_embedded"]}}},
        {},
    ]


def blocked_reason(platform: str, message: str) -> str | None:
    m = message.lower()
    if platform == "Spotify" and ("drm" in m or "protected" in m):
        return (
            "Spotify menolak pengambilan audio karena perlindungan DRM. "
            "Backend ini tidak membypass DRM. Gunakan fitur unduh resmi Spotify Premium."
        )
    if platform == "Snack Video" and ("drm" in m or "protected" in m):
        return (
            "Snack Video menandai media ini sebagai terlindungi/DRM. "
            "yt-dlp tidak dapat mengambil media tersebut tanpa membypass perlindungan."
        )
    if platform == "YouTube" and "sign in to confirm" in m:
        return (
            "YouTube menolak permintaan server karena verifikasi anti-bot. "
            "Percobaan client publik tidak cukup untuk video ini; backend tidak meminta cookie akun Anda."
        )
    return None


def base_opts(audio: bool, output: Path):
    if audio:
        return {
            "format": "bestaudio/best",
            "outtmpl": str(output.with_suffix(".%(ext)s")),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    return {
        "format": "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/best",
        "outtmpl": str(output.with_suffix(".%(ext)s")),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }


def make_opts(url: str, audio: bool, output: Path, strategy: dict | None = None):
    opts = base_opts(audio, output)
    if strategy:
        opts.update(strategy)
    return opts


def extract_download(url: str, audio: bool, output: Path):
    platform = platform_for(url)
    strategies = youtube_strategies() if platform == "YouTube" else [{}]
    errors = []

    for strategy in strategies:
        try:
            opts = make_opts(url, audio, output, strategy)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title") or "Mas Ibram Media"
            return title
        except Exception as exc:
            errors.append(str(exc))

    # Keep the most useful extractor message while limiting response size.
    message = errors[-1] if errors else "Ekstraksi media gagal."
    friendly = blocked_reason(platform, message)
    if friendly:
        raise RuntimeError(friendly)
    if len(errors) > 1 and "Sign in to confirm" in errors[0] and "Sign in to confirm" not in message:
        message = errors[0] + " | Percobaan alternatif juga gagal."
    raise RuntimeError(message[:1400])


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
    return {
        "ok": True,
        "platforms": sorted(set(SUPPORTED.values())),
    }


@app.get("/info")
def info(url: str = Query(...)):
    url = validate_url(url)
    platform = platform_for(url)
    if not platform:
        raise HTTPException(400, "Platform belum didukung.")

    try:
        # For YouTube, try the same public client strategies used by download.
        strategies = youtube_strategies() if platform == "YouTube" else [{}]
        errors = []
        for strategy in strategies:
            try:
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "noplaylist": True,
                }
                opts.update(strategy)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    data = ydl.extract_info(url, download=False)
                return {
                    "ok": True,
                    "platform": platform,
                    "title": data.get("title"),
                    "uploader": data.get("uploader"),
                    "duration": data.get("duration"),
                    "thumbnail": data.get("thumbnail"),
                    "webpage_url": data.get("webpage_url") or url,
                }
            except Exception as exc:
                errors.append(str(exc))
        message = errors[-1] if errors else "Gagal membaca media."
        friendly = blocked_reason(platform, message)
        raise RuntimeError(friendly or message)
    except Exception as e:
        raise HTTPException(502, f"Gagal membaca media: {str(e)[:1000]}")


@app.get("/download")
def download(
    url: str = Query(...),
    media: str = Query("video"),
):
    if media not in ("video", "audio"):
        raise HTTPException(400, "media harus video atau audio.")

    url = validate_url(url)
    platform = platform_for(url)
    if not platform:
        raise HTTPException(400, "Platform belum didukung.")

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
    filename = safe_name(title) + ext
    media_type = "audio/mpeg" if audio else "video/mp4"

    return FileResponse(path, media_type=media_type, filename=filename)
