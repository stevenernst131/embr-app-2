"""
Embr App 2 — TaskForge: A production-grade task management API
Built on FastAPI with PostgreSQL, Valkey cache, and Blob storage
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from contextlib import asynccontextmanager

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration — all sourced from Embr-injected env vars
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
CACHE_URL = os.environ.get("CACHE_URL", "")
BLOB_STORE_URL = os.environ.get("BLOB_STORE_URL", "")
BLOB_API_KEY = os.environ.get("BLOB_API_KEY", "")
APP_ENV = os.environ.get("EMBR_ENVIRONMENT", "unknown")
APP_VERSION = "1.5.0"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("taskforge")

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    """Get a database connection from DATABASE_URL."""
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn

def query_db(sql: str, params=None, fetch_one=False):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if sql.strip().upper().startswith(("SELECT", "WITH")):
                return cur.fetchone() if fetch_one else cur.fetchall()
            if "RETURNING" in sql.upper():
                return cur.fetchone() if fetch_one else cur.fetchall()
            return None
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Cache helpers (Valkey/Redis-compatible)
# ---------------------------------------------------------------------------
_cache_client = None

def get_cache():
    global _cache_client
    if _cache_client is not None:
        return _cache_client
    if not CACHE_URL:
        return None
    try:
        import valkey
        _cache_client = valkey.from_url(CACHE_URL, decode_responses=True)
        _cache_client.ping()
        logger.info("Cache connected via Valkey")
        return _cache_client
    except Exception as e:
        logger.warning(f"Cache unavailable: {e}")
        return None

def cache_get(key: str):
    c = get_cache()
    if c:
        try:
            val = c.get(key)
            return json.loads(val) if val else None
        except Exception:
            return None
    return None

def cache_set(key: str, value, ttl: int = 300):
    c = get_cache()
    if c:
        try:
            c.setex(key, ttl, json.dumps(value, default=str))
        except Exception:
            pass

def cache_delete(pattern: str):
    c = get_cache()
    if c:
        try:
            for k in c.scan_iter(match=pattern):
                c.delete(k)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Blob storage helpers
# ---------------------------------------------------------------------------
def blob_upload(key: str, data: bytes, content_type: str = "application/octet-stream"):
    if not BLOB_STORE_URL or not BLOB_API_KEY:
        return None
    import httpx
    url = f"{BLOB_STORE_URL}/{key}"
    resp = httpx.put(url, content=data, headers={
        "X-Api-Key": BLOB_API_KEY,
        "Content-Type": content_type,
    }, timeout=30)
    resp.raise_for_status()
    return resp.json() if resp.text else {"status": "ok"}

def blob_download(key: str):
    if not BLOB_STORE_URL or not BLOB_API_KEY:
        return None
    import httpx
    url = f"{BLOB_STORE_URL}/{key}"
    resp = httpx.get(url, headers={"X-Api-Key": BLOB_API_KEY}, timeout=30)
    resp.raise_for_status()
    return resp.content

def blob_delete(key: str):
    if not BLOB_STORE_URL or not BLOB_API_KEY:
        return None
    import httpx
    url = f"{BLOB_STORE_URL}/{key}"
    resp = httpx.delete(url, headers={"X-Api-Key": BLOB_API_KEY}, timeout=30)
    return resp.status_code

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=4)
    bio: str = ""

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    owner_id: int
    priority: int = 0

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None

class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    project_id: int
    assigned_to: Optional[int] = None
    priority: int = 0
    due_date: Optional[str] = None

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[int] = None
    priority: Optional[int] = None
    due_date: Optional[str] = None

class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    content: str = ""
    task_id: int
    author_id: Optional[int] = None

class TagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = "#3B82F6"

# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"TaskForge {APP_VERSION} starting in [{APP_ENV}]")
    logger.info(f"DB configured: {bool(DATABASE_URL)}")
    logger.info(f"Cache configured: {bool(CACHE_URL)}")
    logger.info(f"Blob configured: {bool(BLOB_STORE_URL)}")
    # Ensure schema
    if DATABASE_URL:
        try:
            schema_path = os.path.join(os.path.dirname(__file__), "db", "schema.sql")
            if os.path.exists(schema_path):
                with open(schema_path) as f:
                    schema_sql = f.read()
                conn = psycopg2.connect(DATABASE_URL)
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(schema_sql)
                conn.close()
                logger.info("Database schema applied successfully")
        except Exception as e:
            logger.error(f"Schema error: {e}")
    yield
    logger.info("TaskForge shutting down")

app = FastAPI(
    title="TaskForge",
    description="A production-grade task management API built on Embr",
    version=APP_VERSION,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Health & system endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    checks = {"status": "healthy", "version": APP_VERSION, "environment": APP_ENV, "timestamp": datetime.now(timezone.utc).isoformat()}
    # DB check
    try:
        query_db("SELECT 1 AS ok", fetch_one=True)
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {e}"
        checks["status"] = "degraded"
    # Cache check
    c = get_cache()
    if c:
        try:
            c.ping()
            checks["cache"] = "connected"
        except Exception:
            checks["cache"] = "error"
    else:
        checks["cache"] = "not_configured"
    # Blob check
    checks["blob_storage"] = "configured" if BLOB_STORE_URL else "not_configured"
    return checks

@app.get("/")
def root():
    return HTMLResponse("""<!DOCTYPE html>
<html><head><title>TaskForge</title><style>
body{font-family:system-ui;max-width:800px;margin:40px auto;padding:0 20px;background:#0f172a;color:#e2e8f0}
h1{color:#38bdf8}a{color:#818cf8}code{background:#1e293b;padding:2px 6px;border-radius:4px}
.card{background:#1e293b;padding:20px;border-radius:12px;margin:16px 0}
</style></head><body>
<h1>🔨 TaskForge API</h1>
<p>A production-grade task management platform powered by <strong>Embr</strong>.</p>
<div class="card">
<h3>API Endpoints</h3>
<ul>
<li><code>GET /health</code> — Health check with dependency status</li>
<li><code>GET /api/info</code> — System information &amp; capabilities</li>
<li><code>GET /api/stats</code> — Dashboard statistics (cached)</li>
<li><code>POST/GET /api/users</code> — User management</li>
<li><code>POST/GET /api/projects</code> — Project CRUD</li>
<li><code>POST/GET/PUT/DELETE /api/tasks</code> — Full task lifecycle</li>
<li><code>POST/GET /api/notes</code> — Task notes</li>
<li><code>POST/GET /api/tags</code> — Tag management</li>
<li><code>POST /api/tasks/{id}/tags</code> — Tag assignment</li>
<li><code>GET /api/activity</code> — Activity feed</li>
<li><code>POST /api/attachments</code> — File uploads (blob storage)</li>
<li><code>GET /api/search</code> — Full-text search across tasks &amp; projects</li>
<li><code>GET /api/cache/test</code> — Cache read/write verification</li>
<li><code>GET /docs</code> — Interactive OpenAPI docs</li>
</ul>
</div>
<div class="card">
<h3>Environment</h3>
<p>Running in: <code>""" + APP_ENV + """</code> | Version: <code>""" + APP_VERSION + """</code></p>
</div>
</body></html>""")

@app.get("/api/info")
def system_info():
    return {
        "app": "TaskForge",
        "version": APP_VERSION,
        "environment": APP_ENV,
        "platform": "python",
        "framework": "fastapi",
        "features": {
            "database": bool(DATABASE_URL),
            "cache": bool(CACHE_URL),
            "blob_storage": bool(BLOB_STORE_URL),
        },
        "endpoints_count": len(app.routes),
    }

@app.get("/api/stats")
def dashboard_stats():
    cached = cache_get("dashboard_stats")
    if cached:
        cached["_cache"] = "hit"
        return cached
    stats = {}
    try:
        stats["users"] = query_db("SELECT COUNT(*) as c FROM users", fetch_one=True)["c"]
        stats["projects"] = query_db("SELECT COUNT(*) as c FROM projects", fetch_one=True)["c"]
        stats["tasks"] = query_db("SELECT COUNT(*) as c FROM tasks", fetch_one=True)["c"]
        task_breakdown = query_db("SELECT status, COUNT(*) as c FROM tasks GROUP BY status")
        stats["tasks_by_status"] = {r["status"]: r["c"] for r in task_breakdown}
        stats["notes"] = query_db("SELECT COUNT(*) as c FROM notes", fetch_one=True)["c"]
        stats["tags"] = query_db("SELECT COUNT(*) as c FROM tags", fetch_one=True)["c"]
        stats["recent_activity"] = query_db(
            "SELECT COUNT(*) as c FROM activity_log WHERE created_at > NOW() - INTERVAL '24 hours'",
            fetch_one=True
        )["c"]
        stats["_cache"] = "miss"
        cache_set("dashboard_stats", stats, ttl=60)
    except Exception as e:
        stats["error"] = str(e)
    return stats

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@app.post("/api/users", status_code=201)
def create_user(u: UserCreate):
    pw_hash = hashlib.sha256(u.password.encode()).hexdigest()
    try:
        row = query_db(
            "INSERT INTO users (username, email, password_hash, bio) VALUES (%s, %s, %s, %s) RETURNING *",
            (u.username, u.email, pw_hash, u.bio), fetch_one=True
        )
        _log_activity(row["id"], "user_created", "user", row["id"])
        return dict(row)
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(400, "Username or email already exists")

@app.get("/api/users")
def list_users(limit: int = 50, offset: int = 0):
    return query_db("SELECT id, username, email, bio, created_at FROM users ORDER BY id LIMIT %s OFFSET %s", (limit, offset))

@app.get("/api/users/{user_id}")
def get_user(user_id: int):
    row = query_db("SELECT id, username, email, bio, created_at FROM users WHERE id=%s", (user_id,), fetch_one=True)
    if not row:
        raise HTTPException(404, "User not found")
    row = dict(row)
    row["project_count"] = query_db("SELECT COUNT(*) as c FROM projects WHERE owner_id=%s", (user_id,), fetch_one=True)["c"]
    row["task_count"] = query_db("SELECT COUNT(*) as c FROM tasks WHERE assigned_to=%s", (user_id,), fetch_one=True)["c"]
    return row

# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
@app.post("/api/projects", status_code=201)
def create_project(p: ProjectCreate):
    row = query_db(
        "INSERT INTO projects (name, description, owner_id, priority) VALUES (%s,%s,%s,%s) RETURNING *",
        (p.name, p.description, p.owner_id, p.priority), fetch_one=True
    )
    _log_activity(p.owner_id, "project_created", "project", row["id"])
    cache_delete("dashboard_stats")
    return dict(row)

@app.get("/api/projects")
def list_projects(status: Optional[str] = None, limit: int = 50, offset: int = 0):
    if status:
        return query_db("SELECT * FROM projects WHERE status=%s ORDER BY priority DESC, id LIMIT %s OFFSET %s", (status, limit, offset))
    return query_db("SELECT * FROM projects ORDER BY priority DESC, id LIMIT %s OFFSET %s", (limit, offset))

@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    row = query_db("SELECT * FROM projects WHERE id=%s", (project_id,), fetch_one=True)
    if not row:
        raise HTTPException(404, "Project not found")
    row = dict(row)
    row["task_count"] = query_db("SELECT COUNT(*) as c FROM tasks WHERE project_id=%s", (project_id,), fetch_one=True)["c"]
    row["tasks_completed"] = query_db("SELECT COUNT(*) as c FROM tasks WHERE project_id=%s AND status='done'", (project_id,), fetch_one=True)["c"]
    return row

@app.put("/api/projects/{project_id}")
def update_project(project_id: int, p: ProjectUpdate):
    existing = query_db("SELECT * FROM projects WHERE id=%s", (project_id,), fetch_one=True)
    if not existing:
        raise HTTPException(404, "Project not found")
    updates, params = [], []
    for field in ["name", "description", "status", "priority"]:
        val = getattr(p, field)
        if val is not None:
            updates.append(f"{field}=%s")
            params.append(val)
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates.append("updated_at=NOW()")
    params.append(project_id)
    return dict(query_db(f"UPDATE projects SET {','.join(updates)} WHERE id=%s RETURNING *", params, fetch_one=True))

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
@app.post("/api/tasks", status_code=201)
def create_task(t: TaskCreate):
    row = query_db(
        "INSERT INTO tasks (title,description,project_id,assigned_to,priority,due_date) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (t.title, t.description, t.project_id, t.assigned_to, t.priority, t.due_date), fetch_one=True
    )
    _log_activity(t.assigned_to, "task_created", "task", row["id"])
    cache_delete("dashboard_stats")
    return dict(row)

@app.get("/api/tasks")
def list_tasks(
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    assigned_to: Optional[int] = None,
    priority_min: Optional[int] = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    cache_key = f"tasks:{project_id}:{status}:{assigned_to}:{sort}:{order}:{limit}:{offset}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    wheres, params = [], []
    if project_id:
        wheres.append("t.project_id=%s"); params.append(project_id)
    if status:
        wheres.append("t.status=%s"); params.append(status)
    if assigned_to:
        wheres.append("t.assigned_to=%s"); params.append(assigned_to)
    if priority_min is not None:
        wheres.append("t.priority >= %s"); params.append(priority_min)
    where_clause = " WHERE " + " AND ".join(wheres) if wheres else ""
    safe_sort = sort if sort in ("created_at", "priority", "due_date", "title", "status") else "created_at"
    safe_order = "ASC" if order.lower() == "asc" else "DESC"
    params += [limit, offset]
    rows = query_db(
        f"SELECT t.*, u.username as assignee_name FROM tasks t LEFT JOIN users u ON t.assigned_to=u.id{where_clause} ORDER BY t.{safe_sort} {safe_order} LIMIT %s OFFSET %s",
        params
    )
    result = [dict(r) for r in rows]
    cache_set(cache_key, result, ttl=30)
    return result

@app.get("/api/tasks/{task_id}")
def get_task(task_id: int):
    row = query_db(
        "SELECT t.*, u.username as assignee_name FROM tasks t LEFT JOIN users u ON t.assigned_to=u.id WHERE t.id=%s",
        (task_id,), fetch_one=True
    )
    if not row:
        raise HTTPException(404, "Task not found")
    row = dict(row)
    row["notes_count"] = query_db("SELECT COUNT(*) as c FROM notes WHERE task_id=%s", (task_id,), fetch_one=True)["c"]
    row["tags"] = query_db(
        "SELECT tg.* FROM tags tg JOIN task_tags tt ON tg.id=tt.tag_id WHERE tt.task_id=%s", (task_id,)
    )
    row["attachments"] = query_db("SELECT id,filename,content_type,size_bytes,created_at FROM attachments WHERE task_id=%s", (task_id,))
    return row

@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, t: TaskUpdate):
    existing = query_db("SELECT * FROM tasks WHERE id=%s", (task_id,), fetch_one=True)
    if not existing:
        raise HTTPException(404, "Task not found")
    updates, params = [], []
    for field in ["title", "description", "status", "assigned_to", "priority", "due_date"]:
        val = getattr(t, field)
        if val is not None:
            updates.append(f"{field}=%s")
            params.append(val)
    if t.status == "done":
        updates.append("completed_at=NOW()")
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates.append("updated_at=NOW()")
    params.append(task_id)
    row = query_db(f"UPDATE tasks SET {','.join(updates)} WHERE id=%s RETURNING *", params, fetch_one=True)
    _log_activity(None, "task_updated", "task", task_id, {"changes": updates})
    cache_delete("tasks:*")
    cache_delete("dashboard_stats")
    return dict(row)

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    existing = query_db("SELECT * FROM tasks WHERE id=%s", (task_id,), fetch_one=True)
    if not existing:
        raise HTTPException(404, "Task not found")
    query_db("DELETE FROM tasks WHERE id=%s", (task_id,))
    _log_activity(None, "task_deleted", "task", task_id)
    cache_delete("tasks:*")
    cache_delete("dashboard_stats")
    return {"deleted": True, "id": task_id}

# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------
@app.post("/api/notes", status_code=201)
def create_note(n: NoteCreate):
    row = query_db(
        "INSERT INTO notes (title,content,task_id,author_id) VALUES (%s,%s,%s,%s) RETURNING *",
        (n.title, n.content, n.task_id, n.author_id), fetch_one=True
    )
    _log_activity(n.author_id, "note_created", "note", row["id"])
    return dict(row)

@app.get("/api/notes")
def list_notes(task_id: Optional[int] = None, limit: int = 50):
    if task_id:
        return query_db("SELECT n.*, u.username as author_name FROM notes n LEFT JOIN users u ON n.author_id=u.id WHERE n.task_id=%s ORDER BY n.created_at DESC LIMIT %s", (task_id, limit))
    return query_db("SELECT n.*, u.username as author_name FROM notes n LEFT JOIN users u ON n.author_id=u.id ORDER BY n.created_at DESC LIMIT %s", (limit,))

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
@app.post("/api/tags", status_code=201)
def create_tag(t: TagCreate):
    try:
        return dict(query_db("INSERT INTO tags (name,color) VALUES (%s,%s) RETURNING *", (t.name, t.color), fetch_one=True))
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(400, "Tag already exists")

@app.get("/api/tags")
def list_tags():
    return query_db("SELECT * FROM tags ORDER BY name")

@app.post("/api/tasks/{task_id}/tags")
def add_tag_to_task(task_id: int, tag_id: int = Query(...)):
    try:
        query_db("INSERT INTO task_tags (task_id,tag_id) VALUES (%s,%s)", (task_id, tag_id))
        return {"task_id": task_id, "tag_id": tag_id, "status": "added"}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/api/tasks/{task_id}/tags")
def remove_tag_from_task(task_id: int, tag_id: int = Query(...)):
    query_db("DELETE FROM task_tags WHERE task_id=%s AND tag_id=%s", (task_id, tag_id))
    return {"task_id": task_id, "tag_id": tag_id, "status": "removed"}

# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------
def _log_activity(user_id, action, entity_type=None, entity_id=None, details=None):
    try:
        query_db(
            "INSERT INTO activity_log (user_id,action,entity_type,entity_id,details) VALUES (%s,%s,%s,%s,%s)",
            (user_id, action, entity_type, entity_id, json.dumps(details or {}))
        )
    except Exception:
        pass

@app.get("/api/activity")
def activity_feed(limit: int = 50, user_id: Optional[int] = None):
    if user_id:
        return query_db(
            "SELECT a.*, u.username FROM activity_log a LEFT JOIN users u ON a.user_id=u.id WHERE a.user_id=%s ORDER BY a.created_at DESC LIMIT %s",
            (user_id, limit)
        )
    return query_db(
        "SELECT a.*, u.username FROM activity_log a LEFT JOIN users u ON a.user_id=u.id ORDER BY a.created_at DESC LIMIT %s",
        (limit,)
    )

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = 20):
    cache_key = f"search:{q}:{limit}"
    cached = cache_get(cache_key)
    if cached:
        cached["_cache"] = "hit"
        return cached
    pattern = f"%{q}%"
    tasks = query_db(
        "SELECT id, title, description, status, 'task' as type FROM tasks WHERE title ILIKE %s OR description ILIKE %s LIMIT %s",
        (pattern, pattern, limit)
    )
    projects = query_db(
        "SELECT id, name as title, description, status, 'project' as type FROM projects WHERE name ILIKE %s OR description ILIKE %s LIMIT %s",
        (pattern, pattern, limit)
    )
    result = {"query": q, "results": [dict(r) for r in tasks] + [dict(r) for r in projects], "total": len(tasks) + len(projects), "_cache": "miss"}
    cache_set(cache_key, result, ttl=120)
    return result

# ---------------------------------------------------------------------------
# Cache test endpoint
# ---------------------------------------------------------------------------
@app.get("/api/cache/test")
def cache_test():
    c = get_cache()
    if not c:
        return {"cache": "not_available", "message": "CACHE_URL not configured or unreachable"}
    test_key = "embr_cache_test"
    test_val = f"hello_from_taskforge_{int(time.time())}"
    try:
        c.setex(test_key, 60, test_val)
        read_back = c.get(test_key)
        info = c.info()
        return {
            "cache": "working",
            "write": test_val,
            "read": read_back,
            "match": read_back == test_val,
            "server": info.get("redis_version", info.get("server", "unknown")),
            "used_memory_human": info.get("used_memory_human", "?"),
            "connected_clients": info.get("connected_clients", "?"),
        }
    except Exception as e:
        return {"cache": "error", "detail": str(e)}

# ---------------------------------------------------------------------------
# File attachments (blob storage)
# ---------------------------------------------------------------------------
@app.post("/api/attachments", status_code=201)
def upload_attachment(
    task_id: int = Form(...),
    uploaded_by: Optional[int] = Form(None),
    file: UploadFile = File(...),
):
    if not BLOB_STORE_URL:
        raise HTTPException(503, "Blob storage not configured")
    data = file.file.read()
    blob_key = f"attachments/{task_id}/{int(time.time())}_{file.filename}"
    blob_upload(blob_key, data, file.content_type or "application/octet-stream")
    row = query_db(
        "INSERT INTO attachments (task_id,filename,blob_key,content_type,size_bytes,uploaded_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (task_id, file.filename, blob_key, file.content_type, len(data), uploaded_by),
        fetch_one=True
    )
    _log_activity(uploaded_by, "attachment_uploaded", "attachment", row["id"])
    return dict(row)

@app.get("/api/blob/test")
def blob_test():
    """Test blob storage connectivity."""
    if not BLOB_STORE_URL:
        return {"blob": "not_configured"}
    try:
        test_key = "test/connectivity_check.txt"
        test_data = f"TaskForge blob test at {datetime.now(timezone.utc).isoformat()}".encode()
        blob_upload(test_key, test_data, "text/plain")
        read_back = blob_download(test_key)
        blob_delete(test_key)
        return {
            "blob": "working",
            "wrote_bytes": len(test_data),
            "read_bytes": len(read_back) if read_back else 0,
            "match": read_back == test_data if read_back else False,
        }
    except Exception as e:
        return {"blob": "error", "detail": str(e)}

# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------
@app.post("/api/seed")
def seed_data():
    """Seed the database with sample data for demonstration."""
    results = {}
    try:
        # Create users
        users = []
        for i, (name, email) in enumerate([
            ("alice", "alice@taskforge.dev"),
            ("bob", "bob@taskforge.dev"),
            ("charlie", "charlie@taskforge.dev"),
        ]):
            pw_hash = hashlib.sha256(f"pass{name}".encode()).hexdigest()
            try:
                u = query_db(
                    "INSERT INTO users (username,email,password_hash,bio) VALUES (%s,%s,%s,%s) RETURNING id",
                    (name, email, pw_hash, f"Team member {name}"), fetch_one=True
                )
                users.append(u["id"])
            except Exception:
                u = query_db("SELECT id FROM users WHERE username=%s", (name,), fetch_one=True)
                if u:
                    users.append(u["id"])
        results["users_created"] = len(users)

        # Create tags
        tags = []
        for tname, color in [("bug", "#EF4444"), ("feature", "#22C55E"), ("urgent", "#F59E0B"), ("docs", "#6366F1"), ("backend", "#8B5CF6")]:
            try:
                t = query_db("INSERT INTO tags (name,color) VALUES (%s,%s) RETURNING id", (tname, color), fetch_one=True)
                tags.append(t["id"])
            except Exception:
                t = query_db("SELECT id FROM tags WHERE name=%s", (tname,), fetch_one=True)
                if t:
                    tags.append(t["id"])
        results["tags_created"] = len(tags)

        # Create projects
        projects = []
        for pname, desc in [
            ("Platform API", "Core API development"),
            ("Mobile App", "iOS and Android client"),
            ("Infrastructure", "DevOps and cloud infrastructure"),
        ]:
            if users:
                p = query_db(
                    "INSERT INTO projects (name,description,owner_id,priority) VALUES (%s,%s,%s,%s) RETURNING id",
                    (pname, desc, users[0], 5), fetch_one=True
                )
                projects.append(p["id"])
        results["projects_created"] = len(projects)

        # Create tasks
        task_count = 0
        task_data = [
            ("Implement auth middleware", "Add JWT token verification", "in_progress", 8),
            ("Fix database connection pooling", "Connection leaks under load", "todo", 9),
            ("Write API documentation", "Swagger + guides", "todo", 3),
            ("Set up CI/CD pipeline", "GitHub Actions + Embr deploy", "done", 7),
            ("Optimize query performance", "Slow queries on tasks table", "in_progress", 6),
            ("Add rate limiting", "Protect public endpoints", "todo", 5),
            ("Implement search", "Full-text search across entities", "done", 4),
            ("Add blob storage support", "File uploads for attachments", "in_progress", 7),
        ]
        for title, desc, status, priority in task_data:
            if projects and users:
                t = query_db(
                    "INSERT INTO tasks (title,description,project_id,assigned_to,status,priority) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                    (title, desc, projects[task_count % len(projects)], users[task_count % len(users)], status, priority),
                    fetch_one=True
                )
                task_count += 1
                # Add tags
                if tags and t:
                    try:
                        query_db("INSERT INTO task_tags (task_id,tag_id) VALUES (%s,%s)", (t["id"], tags[task_count % len(tags)]))
                    except Exception:
                        pass
        results["tasks_created"] = task_count

        # Create notes
        note_count = 0
        if users:
            for title, content in [
                ("Architecture decision", "Using FastAPI with async endpoints for better throughput"),
                ("Performance findings", "Query optimization reduced p99 latency by 40%"),
                ("Deployment notes", "Embr auto-deploy from main branch working smoothly"),
            ]:
                tasks_list = query_db("SELECT id FROM tasks LIMIT 3")
                if tasks_list and len(tasks_list) > note_count:
                    query_db(
                        "INSERT INTO notes (title,content,task_id,author_id) VALUES (%s,%s,%s,%s)",
                        (title, content, tasks_list[note_count]["id"], users[0])
                    )
                    note_count += 1
        results["notes_created"] = note_count
        cache_delete("dashboard_stats")
        cache_delete("tasks:*")
        results["status"] = "seeded"
    except Exception as e:
        results["error"] = str(e)
    return results

# ---------------------------------------------------------------------------
# Environment debug endpoint
# ---------------------------------------------------------------------------
@app.get("/api/debug/env")
def debug_env():
    """Show non-sensitive environment info for debugging."""
    return {
        "EMBR_ENVIRONMENT": APP_ENV,
        "DATABASE_URL": "configured" if DATABASE_URL else "missing",
        "CACHE_URL": "configured" if CACHE_URL else "missing",
        "BLOB_STORE_URL": "configured" if BLOB_STORE_URL else "missing",
        "BLOB_API_KEY": "configured" if BLOB_API_KEY else "missing",
        "python_version": os.popen("python3 --version 2>&1").read().strip(),
        "pid": os.getpid(),
    }
