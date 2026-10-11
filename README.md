# Mas Ibram Downloader Backend v8

FastAPI + yt-dlp + FFmpeg backend.

Endpoints: `/`, `/health`, `/platforms`, `/info`, `/download`, `/music`.

New recognized domains: FreeReels Drama, Melolo TV, PineDrama, and TeraBox. Recognition does not guarantee extraction: yt-dlp must have a compatible extractor and the link must be publicly accessible. App-only streams, login-gated content, DRM, and access-protected links are not bypassed.

For permanent music, mount a Railway Volume at `/data` and optionally set `ADMIN_API_KEY`.
