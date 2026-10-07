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
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/mas-ibram-downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=APP_NAME, version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED = {
    "youtube.com", "youtu.be", "tiktok.com", "instagram.com",
    "facebook.com", "fb.watch", "twitter.com", "x.com", "spotify.com",
}

def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(400, "URL tidak valid.")
    return url

def host_supported(url: str) -> bool:
    host = urlparse(url).hostname.lower().lstrip("www.")
    return any(host == d or host.endswith("." + d) for d in SUPPORTED)

def safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE).strip()
    return name[:160] or "MasIbram_Media"

def run_yt_dlp(url: str, audio: bool, output: Path):
    if audio:
        opts = {
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
    else:
        opts = {
            "format": "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/best",
            "outtmpl": str(output.with_suffix(".%(ext)s")),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title") or "Mas Ibram Media"

    candidates = sorted(
        [p for p in DOWNLOAD_DIR.glob(output.stem + ".*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("File hasil download tidak ditemukan.")
    return candidates[0], title

@app.get("/")
def root():
    return {"ok": True, "service": APP_NAME, "version": "2.0.0"}

@app.get("/health")
def health():
    return {
        "ok": True,
        "yt_dlp": yt_dlp.version.__version__,
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }

@app.get("/info")
def info(url: str = Query(...)):
    url = validate_url(url)
    if not host_supported(url):
        raise HTTPException(400, "Platform belum didukung.")
    try:
        with yt_dlp.YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
        }) as ydl:
            data = ydl.extract_info(url, download=False)
        return {
            "ok": True,
            "title": data.get("title"),
            "uploader": data.get("uploader"),
            "duration": data.get("duration"),
            "thumbnail": data.get("thumbnail"),
            "webpage_url": data.get("webpage_url") or url,
        }
    except Exception as e:
        raise HTTPException(502, f"Gagal membaca media: {str(e)[:500]}")

@app.get("/download")
def download(
    url: str = Query(...),
    media: str = Query("video"),
):
    if media not in ("video", "audio"):
        raise HTTPException(400, "media harus video atau audio.")

    url = validate_url(url)
    if not host_supported(url):
        raise HTTPException(400, "Platform belum didukung.")

    audio = media == "audio"
    token = next(tempfile._get_candidate_names())
    target = DOWNLOAD_DIR / f"masibram_{token}"

    try:
        path, title = run_yt_dlp(url, audio, target)
    except Exception as e:
        raise HTTPException(502, f"Downloader gagal: {str(e)[:700]}")

    ext = ".mp3" if audio else ".mp4"
    filename = safe_name(title) + ext

    return FileResponse(
        path,
        media_type="audio/mpeg" if audio else "video/mp4",
        filename=filename,
    )
