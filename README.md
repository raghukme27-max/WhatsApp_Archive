# WhatsApp Document Ingestion & Archival System

This project implements a small, production-oriented WhatsApp archive pipeline for document and image intake. It is intended for Windows or macOS deployment and remains portable by relying on configuration rather than machine-specific paths.

## Quick Start (for beginners)

### What this project does
It receives documents and images sent to your WhatsApp business number, downloads them automatically, and saves them into dated folders on your computer. It also keeps track of which messages it has already processed so nothing gets saved twice.

### What you need
- A computer (Windows 10/11 or macOS)
- Python 3.11 or newer installed
- A WhatsApp Business account with access to the WhatsApp Cloud API (Meta developer portal)
- About 15 minutes to set up

### Step 1: Get the project files
If you have Git installed:
```bash
git clone https://github.com/raghukme27-max/WhatsApp_Archive.git
cd WhatsApp_Archive
```

If you don't have Git, download the ZIP file from GitHub and unzip it, then open your terminal/command prompt in that folder.

### Step 2: Create your configuration file
Copy the example configuration file:
```bash
cp .env.example .env
```

Open `.env` in a text editor and fill in these values:
- `WHATSAPP_ACCESS_TOKEN`: Get this from the Meta developer portal (your WhatsApp app → Settings → Tokens)
- `WHATSAPP_VERIFY_TOKEN`: Make up any secret word (for example, `my-whatsapp-secret-123`)
- `ARCHIVE_PATH`: Where you want saved files to go (leave default, or set a folder like `C:\EducationalArchive`)

Save the file and close it.

### Step 3: Run in test mode (safe, no real messages)
```bash
LOCAL_DEV_MODE=true python -m whatsapp_archive
```

You should see `Listening on 127.0.0.1:8000`. Open `http://127.0.0.1:8000/health` in your browser — you should see `{"status": "ok"}`. Press `Ctrl+C` to stop.

### Step 4: Connect WhatsApp (real usage)
1. Go to the Meta developer portal and create a WhatsApp app
2. Add the WhatsApp product and get your access token and phone number ID
3. Set your webhook URL to `https://your-server.com/webhook` and your verify token to match `.env`
4. Update `.env` with your real tokens and set `LOCAL_DEV_MODE=false`
5. Run `python -m whatsapp_archive` again

### Step 5: Run the tests
```bash
python -m unittest discover -s tests
```

You should see all tests pass.

## Features

- Receives WhatsApp Cloud API webhook events
- Verifies webhook subscription challenge requests
- Normalizes WhatsApp message payloads into a small internal model
- Accepts supported document and image types: PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, JPG, JPEG, PNG
- Downloads original media from WhatsApp using the media ID and access token
- Safely stores files in a configurable archive root with collision protection and atomic writes
- Prevents duplicate processing using a persisted processing-state store
- Retries transient failures and logs key events
- Exposes a /health endpoint for operational checks
- Supports a local development/test mode for offline validation

## Supported file extensions

- `.pdf`
- `.doc`
- `.docx`
- `.xls`
- `.xlsx`
- `.ppt`
- `.pptx`
- `.jpg`
- `.jpeg`
- `.png`

Unsupported formats are ignored and logged without blocking the process.

## Configuration

The application reads runtime settings from environment variables. A sample file is included in `.env.example`.

### Environment variables

- `ARCHIVE_PATH` / `WA_ARCHIVE_ROOT`: archive destination, default `~/EducationalArchive` on macOS/Linux and `C:\EducationalArchive` on Windows
- `WEBHOOK_PORT` / `WA_ARCHIVE_PORT`: HTTP port, default `8000`
- `WEBHOOK_HOST` / `WA_ARCHIVE_HOST`: bind address, default `127.0.0.1` (loopback only)
- `WHATSAPP_VERIFY_TOKEN` / `WA_WEBHOOK_VERIFY_TOKEN`: shared token for WhatsApp webhook verification
- `WHATSAPP_WEBHOOK_SECRET` / `WA_WEBHOOK_SECRET`: optional HMAC shared secret for payload authenticity checking
- `WHATSAPP_ACCESS_TOKEN` / `WA_ACCESS_TOKEN`: WhatsApp Cloud API access token for downloading media
- `WHATSAPP_PHONE_NUMBER_ID`: WhatsApp business phone number ID when used by the provider
- `WHATSAPP_API_BASE_URL` / `WA_API_BASE_URL`: optional override for the WhatsApp Graph API base URL, default `https://graph.facebook.com/v18.0`
- `WHATSAPP_API_VERSION`: Meta API version, default `v18.0`
- `LOCAL_DEV_MODE` / `WA_ARCHIVE_LOCAL_MODE`: set to `1` or `true` to enable local development/test mode
- `LOG_LEVEL` / `WA_LOG_LEVEL`: log level, default `INFO`
- `STATE_DB_PATH` / `WA_STATE_DIR`: SQLite state database location, default `ARCHIVE_PATH/.state`
- `MAX_RETRIES` / `WA_MAX_RETRIES`: retry count before permanent failure
- `RETRY_BACKOFF_SECONDS` / `WA_RETRY_BACKOFF_SECONDS`: exponential backoff base delay
- `MAX_WORKERS`: optional operational worker cap for future deployment tuning

### Webhook verification and signature validation

There are two distinct checks:

- Webhook subscription verification: validates the challenge request on `GET /webhook` using the verify token.
- Webhook payload authenticity validation: when `WHATSAPP_WEBHOOK_SECRET` is configured, the application verifies the `X-Hub-Signature-256` SHA256 HMAC against the raw request body before accepting the payload.

The two checks are intentionally separate and do not replace each other.

### Local development mode

When `WA_ARCHIVE_LOCAL_MODE=true`, the application skips live external media fetches and uses a synthetic payload for smoke testing. This is useful for local validation and tests without changing production behavior.

## Running locally

```bash
python -m whatsapp_archive
```

The app exposes:

- `GET /health` — health check
- `GET /webhook` — handles WhatsApp subscription verification
- `POST /webhook` — ingest webhook payloads

## Development and tests

```bash
python -m unittest discover -s tests
```

## Windows Production Deployment

This section is for the office Windows 10/11 production PC. Developer-machine setup is not required once the source files, Python installer, and service-wrapper executable have been supplied.

### Prerequisites and service design

- Windows 10/11, 64-bit, with Windows PowerShell 5.1 (included with Windows).
- Python 3.11 or newer and below 4.0, installed for all users (for example under Program Files). The installer resolves its full executable path and creates a dedicated virtual environment; it rejects a Python interpreter under a user profile and does not depend on whichever `python` happens to be first in `PATH`.
- NSSM 2.24 x64 (`nssm.exe`), obtained separately from the [official NSSM download page](https://nssm.cc/download). Extract `win64\nssm.exe` and pass its path to the installer. NSSM is a small, public-domain Windows service wrapper; it provides Service Control Manager integration, stop handling, restart-on-exit, and bounded stdout/stderr log rotation without adding Windows-specific code or dependencies to the Python application.
- Run installation and removal from an elevated PowerShell session. The service itself runs as the least-privileged built-in `NT AUTHORITY\LOCAL SERVICE` account. The installer grants it read/execute access to the application and modify access to its data, logs, SQLite state, and archive.

The Python app remains independently runnable with `python -m whatsapp_archive`. Windows service management is outside the application. No firewall rule, public listener, tunnel, Meta configuration, or router change is created.

### Installation and configuration

1. Copy the project files to the office PC; Git and VS Code are not needed there. Install Python 3.11+ and obtain the NSSM 2.24 x64 executable.
2. Open PowerShell as Administrator, change to the copied project folder, and run:

   ```powershell
   .\scripts\install_windows.ps1 -NssmPath 'C:\Tools\nssm-2.24\win64\nssm.exe'
   ```

   If Python is not discoverable by the Python launcher or `PATH`, specify its full path with `-PythonExe 'C:\Path\To\python.exe'`. The first run creates `%ProgramData%\WhatsAppArchive\.env` from the example and stops so configuration can be reviewed; this is expected.
3. Edit `%ProgramData%\WhatsAppArchive\.env`. Set `ARCHIVE_PATH` to an absolute path such as `C:\EducationalArchive`, `D:\EducationalArchive`, or `D:\Office Documents\EducationalArchive`; set a private `WHATSAPP_VERIFY_TOKEN`; and set `WEBHOOK_HOST=127.0.0.1`. Configure other credentials only when appropriate. For a local offline smoke test, set `LOCAL_DEV_MODE=true`. Do not put secrets in source control.
4. Rerun the same installer command. It validates configuration, creates the archive/state/log directories, creates the dedicated venv, configures service-account permissions, installs the service, starts it, and runs the health check. Re-running it is safe and keeps the existing `.env`, SQLite state, archive, and documents.

The installer rejects non-loopback `WEBHOOK_HOST` values in this phase. It does not configure Meta or make the endpoint public. `STATE_DB_PATH` is the state **directory** (the application creates `processed_messages.sqlite3` inside it); if omitted by the config, Windows uses `%ProgramData%\WhatsAppArchive\state`. Configuration, SQLite state, and logs are stored under `%ProgramData%\WhatsAppArchive`, separately from both the application (`%ProgramFiles%\WhatsApp Archive`) and document archive.

### Service management and health check

Use the Windows Service Control Manager or elevated PowerShell:

```powershell
Get-Service WhatsAppArchive
Start-Service WhatsAppArchive
Stop-Service WhatsAppArchive
Restart-Service WhatsAppArchive
& (Join-Path $env:ProgramFiles 'WhatsApp Archive\scripts\health_check.ps1')
```

The health check requires the service to be running, checks `GET /health`, verifies archive write access, and runs SQLite `PRAGMA quick_check`. It prints individual `PASS` steps and a final `PASS`, or a specific `FAIL` reason and exits nonzero.

For an offline local development event (with `LOCAL_DEV_MODE=true`), send:

```powershell
$body = '{"entry":[{"changes":[{"value":{"messages":[{"id":"windows-smoke-001","document":{"filename":"smoke.pdf","media_id":"test-media","mime_type":"application/pdf"}}]}}]}]}'
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/webhook' -ContentType 'application/json' -Body $body
```

The resulting file should appear beneath the configured archive. The durable state database is `%ProgramData%\WhatsAppArchive\state\processed_messages.sqlite3` unless `STATE_DB_PATH` is set elsewhere. Back up the database together with the archive; SQLite WAL mode may also create `-wal`/`-shm` files while the service is running, so use a SQLite-aware backup or stop the service before copying the state directory.

### Windows local acceptance sequence

Run these checks on the actual Windows 10/11 office PC; they have not been run from the macOS development machine:

1. Run the installer once to generate `.env`, configure it as described above, then rerun the installer.
2. Confirm `Get-Service WhatsAppArchive` reports `Running`.
3. Run `& (Join-Path $env:ProgramFiles 'WhatsApp Archive\scripts\health_check.ps1')`; require final `PASS`.
4. Send the local development test event shown above while `LOCAL_DEV_MODE=true`.
5. Confirm a new dated file appears under `ARCHIVE_PATH`. This exercises archive writes from the service process, not the elevated health-check shell.
6. Confirm the event is `stored` in `processed_messages.sqlite3`. For the default database location:

   ```powershell
   $python = Join-Path $env:ProgramFiles 'WhatsApp Archive\.venv\Scripts\python.exe'
   $db = Join-Path $env:ProgramData 'WhatsAppArchive\state\processed_messages.sqlite3'
   & $python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('SELECT message_id,status,file_path FROM processing_state').fetchall()); c.close()" $db
   ```

   If `STATE_DB_PATH` is configured explicitly, use that directory in `$db`.
7. Run `Stop-Service WhatsAppArchive`, then `Start-Service WhatsAppArchive`; after each, run the health check and confirm the same row remains in SQLite.
8. For crash recovery, identify the `python.exe` whose command line is `-m whatsapp_archive` (do not terminate unrelated Python processes), then end only that process. NSSM should restart the launcher/application; require the service to return to `Running`, `/health` to pass, and logs to record the restart.
9. Reboot Windows during a maintenance window. After login, confirm the service started automatically, `/health` passes, and the same SQLite row remains.
10. Run the uninstaller only after these checks if validating removal. Confirm the service and application directory are removed while the archive, `%ProgramData%\WhatsAppArchive`, and the SQLite row remain.

### Logs and restart behavior

NSSM captures application stdout/stderr under `%ProgramData%\WhatsAppArchive\logs`. Each log is configured for online rotation at 10 MiB. The application does not log the configured access token, verification token, or HMAC secret.

NSSM restarts the application after an application exit, with a 5-second delay. Windows Service Control Manager recovery actions also restart the service after failures (5, 15, then 60 seconds). The service is configured for automatic startup at boot. The HTTP server waits for active request threads during close, and NSSM allows up to 300 seconds for console shutdown (enough for the default retry window) before its final stop method is used. If `MAX_RETRIES` or `RETRY_BACKOFF_SECONDS` is increased substantially, increase this stop timeout to match.

### Uninstall

From elevated PowerShell, run:

```powershell
& (Join-Path $env:ProgramFiles 'WhatsApp Archive\scripts\uninstall_windows.ps1')
```

The uninstaller stops and removes the service and deletes only the marked application directory, including its venv and bundled NSSM executable. It deliberately preserves `%ProgramData%\WhatsAppArchive` (configuration, logs, and SQLite state), the configured archive directory, and all archived documents. Remove those separately only under an explicit backup/retention procedure.

### Troubleshooting

- **Installer reports a missing Python version:** install Python 3.11+ (64-bit recommended) or pass its full executable path with `-PythonExe`.
- **NSSM is missing:** obtain NSSM 2.24 x64 separately and pass its full `nssm.exe` path using `-NssmPath`.
- **Configuration validation fails:** check that `ARCHIVE_PATH` and a non-placeholder `WHATSAPP_VERIFY_TOKEN` are set, the archive path is absolute, and `WEBHOOK_HOST` is loopback-only.
- **Service fails to start or health check fails:** inspect `%ProgramData%\WhatsAppArchive\logs\service-stderr.log` and `service-stdout.log`, run the health-check script, confirm the port is available, and verify that `LOCAL SERVICE` has access to the archive and state directories.
- **Archive drive is unavailable:** restore/mount the configured drive, then restart the service. The application will not write documents to a different archive root.
- **Local webhook cannot be reached:** confirm the service is running and `WEBHOOK_PORT` matches the URL. This deployment intentionally listens only on loopback.
- **SQLite check fails:** stop the service before repair or backup; do not delete the database or WAL files as a troubleshooting shortcut.

## Security and reliability design notes

- Filenames are sanitized to remove path traversal sequences and invalid characters.
- Writes happen via temporary files and are finalized with atomic replacement.
- Duplicate messages are tracked in the persistent SQLite processing-state database.
- State is reused across application restarts to guard against duplicate processing after crashes.
- Transient network and filesystem problems are retried before failing the event.
