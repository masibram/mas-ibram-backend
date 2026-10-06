import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI(title="Mas Ibram Downloader Backend", version="1.0.0")

# Browser frontend needs to call this API from Netlify.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_URL_LEN = 4000
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "120"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "250"))

ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "instagram.com", "www.instagram.com",
    "facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch",
    "x.com", "www.x.com", "twitter.com", "www.twitter.com",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
}

def valid_url(url: str) -> str:
    url = (url or "").strip()
    if len(url) > MAX_URL_LEN:
        raise HTTPException(400, "URL terlalu panjang.")
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(400, "URL tidak valid.")
    host = p.netloc.lower().split("@")[-1].split(":")[0]
    if not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        raise HTTPException(400, "Platform belum didukung. Gunakan link publik YouTube, TikTok, Instagram, Facebook, atau X.")
    return url

def yt_dlp_bin():
    return shutil.which("yt-dlp") or "yt-dlp"

def run_yt_dlp(url: str, args: list[str], outdir: str):
    cmd = [
        yt_dlp_bin(),
        "--no-playlist",
        "--no-warnings",
        "--restrict-filenames",
        "--socket-timeout", "20",
        "--retries", "2",
        "--fragment-retries", "2",
        "-o", str(Path(outdir) / "%(title).120B.%(ext)s"),
    ] + args + [url]
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=DOWNLOAD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Proses terlalu lama. Coba link lain.")
    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "yt-dlp gagal memproses link.").strip()
        # Avoid exposing a huge command/error dump.
        raise HTTPException(502, msg[-1200:])
    files = [x for x in Path(outdir).glob("*") if x.is_file()]
    if not files:
        raise HTTPException(502, "Media tidak berhasil dibuat.")
    f = max(files, key=lambda x: x.stat().st_mtime)
    if f.stat().st_size > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"File terlalu besar. Batas server {MAX_FILE_MB} MB.")
    return f

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "mas-ibram-downloader",
        "yt_dlp": shutil.which("yt-dlp") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
    }

@app.get("/info")
def info(url: str = Query(..., min_length=8)):
    url = valid_url(url)
    cmd = [yt_dlp_bin(), "--dump-single-json", "--no-warnings", "--skip-download", "--no-playlist", url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Permintaan info timeout.")
    if p.returncode != 0:
        raise HTTPException(502, (p.stderr or "Tidak dapat membaca media.")[-1200:])
    import json
    try:
        data = json.loads(p.stdout)
    except Exception:
        raise HTTPException(502, "Respons metadata tidak valid.")
    return {
        "ok": True,
        "title": data.get("title"),
        "duration": data.get("duration"),
        "thumbnail": data.get("thumbnail"),
        "uploader": data.get("uploader") or data.get("channel"),
        "webpage_url": data.get("webpage_url") or url,
    }

@app.get("/download")
def download(
    url: str = Query(..., min_length=8),
    media: str = Query("video"),
):
    url = valid_url(url)
    media = media.lower().strip()
    if media not in ("video", "audio"):
        raise HTTPException(400, "media harus video atau audio.")

    tempdir = tempfile.mkdtemp(prefix="mas-ibram-")
    try:
        if media == "audio":
            args = [
                "-x",
                "--audio-format", "mp3",
                "--audio-quality", "0",
            ]
        else:
            # Prefer MP4; merge separate audio/video when available.
            args = [
                "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
                "--merge-output-format", "mp4",
            ]

        f = run_yt_dlp(url, args, tempdir)
        safe_name = re.sub(r'[^A-Za-z0-9._ -]+', '', f.name).strip() or ("download.mp3" if media == "audio" else "download.mp4")
        return FileResponse(
            path=f,
            media_type="audio/mpeg" if media == "audio" else "video/mp4",
            filename=safe_name,
            background=None,
        )
    except HTTPException:
        shutil.rmtree(tempdir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tempdir, ignore_errors=True)
        raise HTTPException(500, f"Server error: {str(e)[:500]}")

@app.exception_handler(Exception)
async def generic_error(request, exc):
    return JSONResponse(status_code=500, content={"ok": False, "error": "Internal server error."})
