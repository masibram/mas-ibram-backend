from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os
import re
import tempfile
import shutil
import urllib.request
import urllib.parse
import json
import html
from pathlib import Path
import yt_dlp

app = FastAPI(title="Mas Ibram Downloader Backend", version="5.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED = [
    "CapCut", "Facebook", "Instagram", "Snack Video",
    "Spotify", "TikTok", "Twitter / X", "YouTube"
]

UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36"


def host_of(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def platform_of(url: str) -> str:
    h = host_of(url)
    if h == "youtube.com" or h.endswith(".youtube.com") or h == "youtu.be":
        return "youtube"
    if h == "tiktok.com" or h.endswith(".tiktok.com"):
        return "tiktok"
    if h == "instagram.com" or h.endswith(".instagram.com"):
        return "instagram"
    if h == "facebook.com" or h.endswith(".facebook.com") or h == "fb.watch":
        return "facebook"
    if h == "twitter.com" or h.endswith(".twitter.com") or h == "x.com" or h.endswith(".x.com"):
        return "twitter"
    if h == "spotify.com" or h.endswith(".spotify.com"):
        return "spotify"
    if h == "capcut.com" or h.endswith(".capcut.com") or h == "capcut.cn" or h.endswith(".capcut.cn"):
        return "capcut"
    if h == "snackvideo.com" or h.endswith(".snackvideo.com"):
        return "snackvideo"
    return "unknown"


def resolve_redirect(url: str) -> str:
    """Follow short-link redirects, especially Snack Video share URLs."""
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


def youtube_option_sets():
    # Try several public clients. None of these bypasses account authentication
    # or DRM; they simply use yt-dlp's supported extractor clients.
    return [
        {},
        {"extractor_args": {"youtube": {"player_client": ["android_vr"]}}},
        {"extractor_args": {"youtube": {"player_client": ["web_safari"]}}},
        {"extractor_args": {"youtube": {"player_client": ["tv"]}}},
    ]


def base_ydl_opts(tmpdir: str):
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": False,
        "outtmpl": str(Path(tmpdir) / "%(title)s.%(ext)s"),
        "http_headers": {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,id;q=0.8"},
    }


def extract_info(url: str):
    platform = platform_of(url)
    attempts = youtube_option_sets() if platform == "youtube" else [{}]
    last = None
    for extra in attempts:
        opts = base_ydl_opts(tempfile.gettempdir())
        opts.update(extra)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info, extra
        except Exception as e:
            last = e
    raise last or RuntimeError("Gagal membaca media")


def friendly_error(exc: Exception, platform: str) -> str:
    msg = str(exc)
    low = msg.lower()
    if platform == "spotify" and ("drm" in low or "protected" in low or "not supported" in low):
        return "Spotify menolak pengambilan audio karena perlindungan DRM. Backend ini tidak membypass DRM. Gunakan fitur unduh resmi Spotify Premium."
    if platform == "youtube" and ("sign in to confirm" in low or "not a bot" in low or "cookies" in low or "authentication" in low):
        return "YouTube menolak permintaan server karena verifikasi anti-bot. Percobaan client publik tidak cukup untuk video ini; backend tidak meminta cookie akun Anda."
    if platform == "snackvideo" and ("unsupported url" in low or "no suitable extractor" in low):
        return "Snack Video masih mengembalikan halaman yang tidak dapat dibaca yt-dlp setelah redirect. Link pendek sudah diikuti, tetapi extractor Snack Video tidak menemukan media publiknya."
    if "unsupported url" in low:
        return f"URL {platform} belum dapat dibaca oleh extractor yt-dlp saat ini."
    return msg[:1200]


@app.get("/")
def root():
    return {"ok": True, "service": "Mas Ibram Downloader Backend", "version": "5.0.0", "platforms": SUPPORTED}


@app.get("/health")
def health():
    return {"ok": True, "service": "Mas Ibram Downloader Backend", "version": "5.0.0", "yt_dlp": yt_dlp.version.__version__, "ffmpeg": shutil.which("ffmpeg") is not None, "platforms": SUPPORTED}


@app.get("/info")
def info(url: str = Query(..., min_length=5)):
    resolved = resolve_redirect(url)
    platform = platform_of(resolved)
    if platform == "spotify":
        # Let yt-dlp confirm whether a public item is usable, but surface a
        # clear DRM message instead of pretending the backend can bypass it.
        try:
            data, _ = extract_info(resolved)
        except Exception as e:
            raise HTTPException(status_code=400, detail=friendly_error(e, platform))
    try:
        data, selected = extract_info(resolved)
    except Exception as e:
        raise HTTPException(status_code=400, detail=friendly_error(e, platform))

    return {
        "ok": True,
        "platform": platform,
        "input_url": url,
        "resolved_url": resolved,
        "title": data.get("title"),
        "thumbnail": data.get("thumbnail"),
        "duration": data.get("duration"),
        "uploader": data.get("uploader") or data.get("channel"),
    }


@app.get("/download")
def download(
    url: str = Query(..., min_length=5),
    media: str = Query("video", pattern="^(video|audio)$"),
):
    resolved = resolve_redirect(url)
    platform = platform_of(resolved)

    if platform == "spotify":
        # Spotify DRM is intentionally not bypassed.
        raise HTTPException(
            status_code=400,
            detail="Spotify menolak pengambilan audio karena perlindungan DRM. Backend ini tidak membypass DRM. Gunakan fitur unduh resmi Spotify Premium.",
        )

    work = tempfile.mkdtemp(prefix="masibram-")
    try:
        option_sets = youtube_option_sets() if platform == "youtube" else [{}]
        last = None
        chosen = None
        for extra in option_sets:
            opts = base_ydl_opts(work)
            opts.update(extra)
            opts["format"] = "bestaudio/best" if media == "audio" else "bestvideo*+bestaudio/best"
            if media == "audio":
                opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([resolved])
                chosen = extra
                break
            except Exception as e:
                last = e

        if chosen is None:
            raise last or RuntimeError("Download gagal")

        files = [p for p in Path(work).iterdir() if p.is_file()]
        if not files:
            raise RuntimeError("Server selesai memproses tetapi file output tidak ditemukan.")
        # Prefer the newest/largest media file.
        output = max(files, key=lambda p: p.stat().st_size)
        suffix = ".mp3" if media == "audio" else output.suffix
        filename = re.sub(r"[\\/:*?\"<>|]+", "_", output.stem).strip() or "MasIbram_Media"
        if suffix and not filename.lower().endswith(suffix.lower()):
            filename += suffix

        response = FileResponse(
            path=str(output),
            media_type="audio/mpeg" if media == "audio" else "video/mp4",
            filename=filename,
        )
        # Cleanup after the response is sent is platform-dependent; the small
        # temp file can safely remain until the container is recycled.
        return response
    except Exception as e:
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(status_code=400, detail=friendly_error(e, platform))
