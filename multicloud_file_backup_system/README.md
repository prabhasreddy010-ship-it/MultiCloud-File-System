# Multi-Cloud File Backup System

A Flask-based, GitHub-ready implementation of the uploaded PBL report. It demonstrates multi-cloud-style backup replication, version history, SHA-256 integrity checking, restore failover, retention, login, role-based administration, and a browser dashboard.

## Features

- Upload a file and create a numbered backup version.
- Replicate each backup to 1–3 independent provider storage areas (AWS S3, Azure Blob, Google Cloud **simulated locally**).
- Maintain a SQLite backup catalog with file name, version, checksum, size, timestamp, and copy locations.
- Restore a selected version; try copies in sequence and return a file only when its SHA-256 checksum matches.
- Verify all copies and mark corrupted/missing copies.
- Retention policy removes older versions and their stored copies.
- Login with password hashing, user/admin roles, and admin screens for users and backup policy.
- Responsive web dashboard and health endpoint.

> Important: This edition is fully executable without paid cloud accounts. Provider folders emulate independent cloud storage for academic demonstration. It does not upload to real AWS/Azure/GCP until real SDK connectors and credentials are configured.

## Requirements

- Python 3.10+
- pip

## Run on Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
py app.py
```

Open http://127.0.0.1:5000

## Run on macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## First login

- Username: `admin`
- Password: `Admin@123`

Change the default password before using this outside a local demo. Set `ADMIN_PASSWORD` and `SECRET_KEY` environment variables before the first run. The initial admin account is created only when the database is first initialized.

## Project structure

```text
multicloud-file-backup-system/
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
├── templates/
│   ├── base.html
│   ├── login.html
│   └── index.html
├── static/
│   └── style.css
└── data/                 # created automatically; excluded from Git
    ├── catalog.db
    └── clouds/
        ├── aws/
        ├── azure/
        └── gcp/
```

## How to demonstrate

1. Sign in as admin.
2. Upload a small text or PDF file. The catalog shows its version and checksum.
3. Upload the same file again to create version 2.
4. Change the backup policy to retain one version, then upload another version to demonstrate retention.
5. Click **Verify all copies** to validate SHA-256 checksums.
6. Restore an earlier version from the catalog.
7. For a failover demonstration, stop the app, remove one copy file under `data/clouds/`, restart, and restore. The system tries the remaining copy. (Do not remove files from a real backup.)

## GitHub publishing

Create an empty GitHub repository, then run these commands from this project folder:

```bash
git init
git add .
git commit -m "Initial Multi-Cloud File Backup System"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/multicloud-file-backup-system.git
git push -u origin main
```

Do not commit `.env`, `data/`, cloud credentials, or real user backup files.

## Production hardening before public deployment

This is a student project/demo, not a hardened production backup service. Before exposing it to the internet:
- Replace the default admin password and secret key.
- Add CSRF protection, rate limiting, HTTPS, secure cookie settings, audit logging, and stronger session controls.
- Use a production WSGI server and a managed database.
- Add real provider SDK connectors, encryption at rest/in transit, credential management, lifecycle policies, and cloud IAM least privilege.
- Add automated tests, monitoring, backup catalog recovery, and disaster-recovery drills.

## Mapping to the report

| Report module | Implementation |
|---|---|
| User authentication | Flask session login + Werkzeug password hashing |
| Admin module | Admin user creation and policy settings |
| Cloud provider module | Provider-specific local storage emulators |
| Backup and replication | Versioned upload replicated to configured number of providers |
| Backup catalog | SQLite `backups` and `copies` tables |
| Restore and failover | Tries copies in order and validates checksum |
| Integrity verification | SHA-256 verification for every stored copy |
| Retention and display | Configurable version retention + dashboard |

## License

For academic/demo use. Add a license file if you choose a specific open-source license.
