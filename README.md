# Mas Ibram Downloader Backend v8.1

FastAPI + yt-dlp backend. This patch adds domain recognition for the exact shared links supplied for FreeReels Drama (`apiv2.free-reels.com`), Melolo TV (`www.melolo.org`), PineDrama (`shortdrama.tiktok.com`), and TeraBox (`terabox.com`, `1024terabox.com`).

## Important limitation
Recognizing a domain only removes the frontend/backend “platform unsupported” rejection. It does not guarantee extraction: the installed yt-dlp must have a working extractor for the service, and some services may require app APIs, authentication, region access, or DRM. Do not bypass DRM or access controls. Test with public links.

## Deploy
Replace `app.py`, `requirements.txt`, `Dockerfile`, and `README.md` in the root of the existing GitHub repository. Keep the same Railway service and existing `/data` volume for music configuration.

Health: `/health`
Supported-domain listing: `/platforms`
