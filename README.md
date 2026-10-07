# Mas Ibram Downloader Backend

Backend FastAPI untuk frontend Mas Ibram Downloader.

## Endpoint

- `GET /health`
- `GET /info?url=...`
- `GET /download?url=...&media=video`
- `GET /download?url=...&media=audio`

## Docker

Container sudah memasang FFmpeg dan membaca port dari environment `PORT`.

Jika platform meminta **Root Directory**, kosongkan karena file berada di root repository.

## Tes setelah live

Buka:

`https://DOMAIN-BACKEND/health`

Harus muncul JSON dengan `"ok": true` dan `"ffmpeg": true`.

## Catatan

Gunakan hanya untuk konten yang memang boleh Anda unduh. Keberhasilan tetap bergantung pada perubahan platform sumber, login/cookies, pembatasan region, dan jenis URL.
