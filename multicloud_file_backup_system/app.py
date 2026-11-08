import os, sqlite3, hashlib, uuid, shutil
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DB = DATA / "catalog.db"
STORAGE = DATA / "clouds"
UPLOADS = DATA / "uploads"
for p in (DATA, STORAGE, UPLOADS): p.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-deployment")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
PROVIDERS = {"AWS S3 (simulated)": "aws", "Azure Blob (simulated)": "azure", "Google Cloud (simulated)": "gcp"}
DEFAULT_COPIES = int(os.environ.get("BACKUP_COPIES", "2"))
DEFAULT_RETENTION = int(os.environ.get("RETENTION_VERSIONS", "5"))

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT);
        CREATE TABLE IF NOT EXISTS backups(
          id INTEGER PRIMARY KEY, file_name TEXT NOT NULL, version INTEGER NOT NULL,
          checksum TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL,
          user_id INTEGER, UNIQUE(file_name, version));
        CREATE TABLE IF NOT EXISTS copies(
          id INTEGER PRIMARY KEY, backup_id INTEGER NOT NULL, provider TEXT NOT NULL,
          object_path TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'healthy',
          FOREIGN KEY(backup_id) REFERENCES backups(id));
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)
        if not con.execute("SELECT id FROM users WHERE username='admin'").fetchone():
            con.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)",
                        ("admin", generate_password_hash(os.environ.get("ADMIN_PASSWORD","Admin@123")), "admin"))
        for k,v in (("copies",str(DEFAULT_COPIES)),("retention",str(DEFAULT_RETENTION))):
            con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
        for name,slug in PROVIDERS.items():
            (STORAGE/slug).mkdir(parents=True, exist_ok=True)

def setting(key):
    with db() as con:
        row=con.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
    return row["value"] if row else ""

def login_required(fn):
    @wraps(fn)
    def wrapper(*a,**kw):
        if "user_id" not in session: return redirect(url_for("login"))
        return fn(*a,**kw)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a,**kw):
        if session.get("role") != "admin": abort(403)
        return fn(*a,**kw)
    return wrapper

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def next_version(name):
    with db() as con:
        r=con.execute("SELECT COALESCE(MAX(version),0)+1 AS v FROM backups WHERE file_name=?",(name,)).fetchone()
    return r["v"]

def store_copy(src, provider_slug, object_name):
    dest=STORAGE/provider_slug/object_name
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src,dest)
    return str(dest.relative_to(BASE))

def backup_file(src, original_name, user_id):
    name=secure_filename(original_name) or "uploaded_file"
    version=next_version(name)
    checksum=sha256(src)
    size=os.path.getsize(src)
    with db() as con:
        cur=con.execute("INSERT INTO backups(file_name,version,checksum,size,created_at,user_id) VALUES(?,?,?,?,?,?)",
          (name,version,checksum,size,datetime.now(timezone.utc).isoformat(timespec="seconds"),user_id))
        bid=cur.lastrowid
    # Simulated cloud connectors: independent provider directories.
    available=list(PROVIDERS.items())
    copies=max(1,min(3,int(setting("copies") or 2)))
    for provider,slug in available[:copies]:
        object_name=f"{uuid.uuid4().hex}_{name}"
        rel=store_copy(src,slug,object_name)
        with db() as con:
            con.execute("INSERT INTO copies(backup_id,provider,object_path,status) VALUES(?,?,?,'healthy')",(bid,provider,rel))
    apply_retention(name)
    return bid, version, checksum

def apply_retention(name):
    keep=max(1,int(setting("retention") or 5))
    with db() as con:
        old=con.execute("SELECT id FROM backups WHERE file_name=? ORDER BY version DESC LIMIT -1 OFFSET ?",(name,keep)).fetchall()
        for row in old:
            copies=con.execute("SELECT object_path FROM copies WHERE backup_id=?",(row["id"],)).fetchall()
            for c in copies:
                try: (BASE/c["object_path"]).unlink(missing_ok=True)
                except OSError: pass
            con.execute("DELETE FROM copies WHERE backup_id=?",(row["id"],))
            con.execute("DELETE FROM backups WHERE id=?",(row["id"],))

def restore_backup(backup_id, destination):
    with db() as con:
        b=con.execute("SELECT * FROM backups WHERE id=?",(backup_id,)).fetchone()
        copies=con.execute("SELECT * FROM copies WHERE backup_id=? ORDER BY id",(backup_id,)).fetchall()
    if not b: raise ValueError("Backup version not found.")
    for c in copies:
        path=BASE/c["object_path"]
        if not path.exists(): continue
        if sha256(path)==b["checksum"]:
            shutil.copy2(path,destination)
            return c["provider"]
        with db() as con: con.execute("UPDATE copies SET status='corrupted' WHERE id=?",(c["id"],))
    raise ValueError("No healthy, checksum-valid copy is available.")

@app.route("/")
def index():
    if "user_id" not in session: return redirect(url_for("login"))
    with db() as con:
        backups=con.execute("""SELECT b.*,u.username,
          (SELECT COUNT(*) FROM copies c WHERE c.backup_id=b.id) AS copy_count
          FROM backups b LEFT JOIN users u ON u.id=b.user_id ORDER BY b.created_at DESC""").fetchall()
        users=con.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    return render_template("index.html",backups=backups,providers=list(PROVIDERS),users=users,
                           copies=setting("copies"),retention=setting("retention"))

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        with db() as con:
            u=con.execute("SELECT * FROM users WHERE username=?",(request.form.get("username",""),)).fetchone()
        if u and check_password_hash(u["password"],request.form.get("password","")):
            session.update(user_id=u["id"],username=u["username"],role=u["role"])
            return redirect(url_for("index"))
        flash("Invalid username or password.","error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/backup",methods=["POST"])
@login_required
def upload_backup():
    f=request.files.get("file")
    if not f or not f.filename:
        flash("Choose a file first.","error"); return redirect(url_for("index"))
    temp=UPLOADS/(uuid.uuid4().hex+"_"+secure_filename(f.filename))
    f.save(temp)
    try:
        bid,version,checksum=backup_file(temp,f.filename,session["user_id"])
        flash(f"Backup successful: version {version}, SHA-256 {checksum[:16]}…","success")
    except Exception as e: flash(f"Backup failed: {e}","error")
    finally: temp.unlink(missing_ok=True)
    return redirect(url_for("index"))

@app.route("/restore/<int:backup_id>")
@login_required
def restore(backup_id):
    with db() as con:
        b=con.execute("SELECT file_name,version FROM backups WHERE id=?",(backup_id,)).fetchone()
    if not b: abort(404)
    out=UPLOADS/(uuid.uuid4().hex+"_"+b["file_name"])
    try:
        provider=restore_backup(backup_id,out)
        flash(f"Restored version {b['version']} using {provider}.","success")
        return send_file(out,as_attachment=True,download_name=b["file_name"])
    except ValueError as e:
        flash(str(e),"error"); return redirect(url_for("index"))
    finally:
        # send_file streams after response; temporary file cleanup is handled by OS/manual cleanup.
        pass

@app.route("/verify",methods=["POST"])
@login_required
def verify():
    checked=0; damaged=0
    with db() as con:
        rows=con.execute("""SELECT c.id,c.object_path,b.checksum FROM copies c
          JOIN backups b ON b.id=c.backup_id""").fetchall()
    for r in rows:
        p=BASE/r["object_path"]
        ok=p.exists() and sha256(p)==r["checksum"]
        checked+=1
        with db() as con: con.execute("UPDATE copies SET status=? WHERE id=?",("healthy" if ok else "corrupted",r["id"]))
        if not ok: damaged+=1
    flash(f"Integrity check complete: {checked} copies checked, {damaged} corrupted or missing.","success" if not damaged else "error")
    return redirect(url_for("index"))

@app.route("/admin/settings",methods=["POST"])
@login_required
@admin_required
def update_settings():
    copies=max(1,min(3,int(request.form.get("copies",2))))
    retention=max(1,min(100,int(request.form.get("retention",5))))
    with db() as con:
        con.execute("UPDATE settings SET value=? WHERE key='copies'",(str(copies),))
        con.execute("UPDATE settings SET value=? WHERE key='retention'",(str(retention),))
    flash("Backup settings updated. They apply to future backups.","success")
    return redirect(url_for("index"))

@app.route("/admin/users",methods=["POST"])
@login_required
@admin_required
def create_user():
    username=request.form.get("username","").strip()
    password=request.form.get("password","")
    role=request.form.get("role","user")
    if not username or len(password)<8 or role not in ("user","admin"):
        flash("Enter a username and password (minimum 8 characters).","error")
    else:
        try:
            with db() as con:
                con.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)",
                            (username,generate_password_hash(password),role))
            flash("User created.","success")
        except sqlite3.IntegrityError: flash("Username already exists.","error")
    return redirect(url_for("index"))

@app.route("/health")
def health():
    return {"status":"ok","service":"Multi-Cloud File Backup System"}

if __name__=="__main__":
    init_db()
    app.run(host="127.0.0.1",port=int(os.environ.get("PORT",5000)),debug=False)
