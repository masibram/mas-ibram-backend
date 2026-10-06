# Mas Ibram Downloader Backend

Backend FastAPI untuk frontend Netlify.

## Endpoint

- `GET /health`
- `GET /info?url=...`
- `GET /download?url=...&media=video`
- `GET /download?url=...&media=audio`

Backend memakai `yt-dlp` + FFmpeg di server sehingga frontend tidak lagi bergantung pada CORS/public downloader APIs.

## Deploy

Container membutuhkan Python, yt-dlp, dan FFmpeg. Deploy sebagai Docker Web Service pada provider yang mendukung container.

Setelah live, buka:

`https://DOMAIN-BACKEND/health`

Harus mengembalikan JSON dengan `"ok": true`.

## Catatan

Hanya gunakan konten yang memang boleh Anda unduh. Hasil tetap bergantung pada akses publik platform sumber, perubahan platform, dan kapasitas server.
