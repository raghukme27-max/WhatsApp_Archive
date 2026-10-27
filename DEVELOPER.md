# Developer Notes

## Quick start

### Run the app locally
```bash
python -m whatsapp_archive
```
The server listens on `http://127.0.0.1:8000` by default.

### Enable local development mode
```bash
LOCAL_DEV_MODE=true python -m whatsapp_archive
```
This skips live WhatsApp media downloads and uses synthetic payloads for testing.

### Run tests
```bash
python -m unittest discover -s tests
```

## Project structure
- `whatsapp_archive/__main__.py` — entry point (`python -m whatsapp_archive`)
- `whatsapp_archive/server.py` — HTTP server and webhook handlers
- `whatsapp_archive/whatsapp.py` — WhatsApp API client, signature verification, payload normalization
- `whatsapp_archive/archive.py` — message processing, retries, deduplication
- `whatsapp_archive/storage.py` — safe file writes, filename sanitization, collision protection
- `whatsapp_archive/state.py` — SQLite processing-state database
- `whatsapp_archive/config.py` — environment-variable configuration
- `whatsapp_archive/models.py` — normalized message and archive result data models
- `tests/test_core.py` — unit tests
- `scripts/` — Windows PowerShell installer and service scripts

## Environment variables
Copy `.env.example` to `.env` and edit it:
- `ARCHIVE_PATH` — where archived files are stored
- `WEBHOOK_PORT` / `WEBHOOK_HOST` — HTTP bind address (default loopback only)
- `WHATSAPP_VERIFY_TOKEN` — webhook subscription verification token
- `WHATSAPP_ACCESS_TOKEN` — WhatsApp Cloud API access token
- `LOCAL_DEV_MODE` — set to `true` for offline testing

## Important
- Never commit `.env` or any file containing real tokens/secrets.
- `.env.example` is safe to commit because it only contains placeholder values.
