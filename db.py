"""
db.py — User progress tracking for Tupelo Nursing Exam Prep.

SQLite-backed storage for users, quiz sessions, answers, and readiness scores.
Uses only stdlib sqlite3 — no ORM, no external dependencies.
Adapted from TEAS Study Buddy pattern.
"""

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "user_progress.db")


def _get_conn():
    """Return a connection with Row factory and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")   # wait, don't error, if another writer holds the lock
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist. Safe to call multiple times."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                email           TEXT UNIQUE,
                password_hash   TEXT,
                access_token    TEXT,
                display_name    TEXT NOT NULL DEFAULT 'Student',
                exam_date       TEXT,
                target_score    INTEGER DEFAULT 80,
                is_anonymous    INTEGER NOT NULL DEFAULT 0,
                onboarding_done INTEGER NOT NULL DEFAULT 0,
                plan            TEXT NOT NULL DEFAULT 'free',
                premium_until   TEXT,
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL DEFAULT 1,
                domain          TEXT NOT NULL,
                num_questions   INTEGER NOT NULL,
                score           INTEGER NOT NULL DEFAULT 0,
                total           INTEGER NOT NULL DEFAULT 0,
                pct             REAL NOT NULL DEFAULT 0.0,
                started_at      TEXT NOT NULL,
                finished_at     TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS answers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL DEFAULT 1,
                session_id      INTEGER NOT NULL,
                question_id     INTEGER NOT NULL,
                question_text   TEXT NOT NULL,
                selected_answer TEXT NOT NULL,
                correct_answer  TEXT NOT NULL,
                is_correct      INTEGER NOT NULL DEFAULT 0,
                confidence      INTEGER DEFAULT NULL,
                time_elapsed    INTEGER NOT NULL DEFAULT 0,
                answered_at     TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (session_id) REFERENCES quiz_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS topic_mastery (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL DEFAULT 1,
                domain          TEXT NOT NULL,
                topic           TEXT NOT NULL,
                total_attempted INTEGER NOT NULL DEFAULT 0,
                total_correct   INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, domain, topic),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS review_queue (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL DEFAULT 1,
                question_id     INTEGER NOT NULL,
                domain          TEXT NOT NULL,
                topic           TEXT NOT NULL,
                next_review     TEXT NOT NULL,
                interval_days   REAL NOT NULL DEFAULT 1.0,
                ease_factor     REAL NOT NULL DEFAULT 2.5,
                times_correct   INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, question_id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        _migrate_add_column(conn, "users", "plan", "TEXT NOT NULL DEFAULT 'free'")
        _migrate_add_column(conn, "users", "premium_until", "TEXT")
        _migrate_add_column(conn, "users", "access_token", "TEXT")
        _migrate_add_column(conn, "users", "signup_source", "TEXT")   # partner/channel attribution (?src=)

        # ORDER-style unique token index (registered-user dashboard links).
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_access_token ON users(access_token)")

        # Pilot waitlist — collected when the RC #1 signup cap is reached.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS waitlist (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT NOT NULL UNIQUE,
                source      TEXT DEFAULT 'pilot_full',
                created_at  TEXT NOT NULL
            )
        """)

        # Socratic Tutor chat history — persisted across sessions so the
        # unified Coach page can hydrate the student's prior conversation.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tutor_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL DEFAULT 1,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                domain      TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # FCLE one-time pricing flip (Sep 6, 2026): map any legacy fcle_monthly
        # grants to annual for goodwill (expect 0 — free-launch shipped no grants).
        legacy = conn.execute("SELECT id FROM users WHERE plan='fcle_monthly'").fetchall()
        if legacy:
            until = (datetime.utcnow() + timedelta(days=365)).isoformat()
            conn.execute(
                "UPDATE users SET plan='fcle_annual_12', premium_until=? WHERE plan='fcle_monthly'",
                (until,),
            )

        conn.commit()


def _migrate_add_column(conn, table, column, col_type):
    """Add a column to a table if it doesn't exist."""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


# ---------------------------------------------------------------------------
# Session & Answer Tracking
# ---------------------------------------------------------------------------

def create_session(user_id, domain, num_questions):
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO quiz_sessions (user_id, domain, num_questions, started_at) VALUES (?, ?, ?, ?)",
            (user_id, domain, num_questions, now),
        )
        conn.commit()
        return cur.lastrowid


def record_answer(user_id, session_id, question_id, question_text, selected, correct, is_correct, time_elapsed, confidence=None):
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO answers
               (user_id, session_id, question_id, question_text, selected_answer, correct_answer, is_correct, confidence, time_elapsed, answered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, session_id, question_id, question_text, selected, correct, int(is_correct), confidence, time_elapsed, now),
        )
        conn.commit()
        return cur.lastrowid


def finish_session(session_id, score, total, pct):
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE quiz_sessions SET score=?, total=?, pct=?, finished_at=? WHERE id=?",
            (score, total, pct, now, session_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Readiness & Stats
# ---------------------------------------------------------------------------

def get_readiness(user_id, domain):
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT SUM(total_correct) AS c, SUM(total_attempted) AS a FROM topic_mastery WHERE user_id=? AND domain=?",
            (user_id, domain),
        ).fetchone()
        if row["a"] and row["a"] > 0:
            return round(row["c"] / row["a"] * 100, 1)
        row2 = conn.execute(
            """SELECT COUNT(*) AS a,
                      SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS c
               FROM answers a2
               JOIN quiz_sessions s ON a2.session_id = s.id
               WHERE a2.user_id=? AND s.domain = ?""",
            (user_id, domain),
        ).fetchone()
        if row2["a"] and row2["a"] > 0:
            return round(row2["c"] / row2["a"] * 100, 1)
        return 0.0


def get_topic_readiness(user_id, domain, topic):
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT total_correct, total_attempted FROM topic_mastery WHERE user_id=? AND domain=? AND topic=?",
            (user_id, domain, topic),
        ).fetchone()
        if row and row["total_attempted"] > 0:
            return round(row["total_correct"] / row["total_attempted"] * 100, 1)
        return 0.0


def get_recent_sessions(user_id, limit=5):
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT id, domain, num_questions, score, total, pct, started_at, finished_at
               FROM quiz_sessions
               WHERE user_id=? AND finished_at IS NOT NULL
               ORDER BY id DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_subject_stats(user_id, domain):
    """Stats for a domain including per-topic breakdown."""
    with _get_conn() as conn:
        overall = conn.execute(
            "SELECT SUM(total_attempted) AS a, SUM(total_correct) AS c FROM topic_mastery WHERE user_id=? AND domain=?",
            (user_id, domain),
        ).fetchone()

        total_attempted = overall["a"] or 0
        total_correct = overall["c"] or 0
        readiness_pct = round(total_correct / total_attempted * 100, 1) if total_attempted > 0 else 0.0

        topic_rows = conn.execute(
            "SELECT topic, total_attempted, total_correct FROM topic_mastery WHERE user_id=? AND domain=? ORDER BY topic",
            (user_id, domain),
        ).fetchall()
        topics = []
        for tr in topic_rows:
            ta = tr["total_attempted"] or 0
            tc = tr["total_correct"] or 0
            topics.append({
                "topic": tr["topic"],
                "total": ta,
                "correct": tc,
                "pct": round(tc / ta * 100, 1) if ta > 0 else 0.0,
            })

        return {
            "total_attempted": total_attempted,
            "total_correct": total_correct,
            "readiness_pct": readiness_pct,
            "topics": topics,
        }


def get_overall_stats(user_id):
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT domain, SUM(total_attempted) AS a, SUM(total_correct) AS c FROM topic_mastery WHERE user_id=? GROUP BY domain ORDER BY domain",
            (user_id,),
        ).fetchall()

        domains = []
        grand_attempted = 0
        grand_correct = 0
        for r in rows:
            a = r["a"] or 0
            c = r["c"] or 0
            grand_attempted += a
            grand_correct += c
            domains.append({
                "name": r["domain"],
                "slug": r["domain"].lower().replace(" ", "-"),
                "readiness_pct": round(c / a * 100, 1) if a > 0 else 0.0,
            })

        overall_readiness = round(grand_correct / grand_attempted * 100, 1) if grand_attempted > 0 else 0.0

        return {
            "overall_readiness": overall_readiness,
            "domains": domains,
        }


def get_weekly_activity(user_id):
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT DATE(started_at) AS day, COUNT(*) AS count
               FROM quiz_sessions
               WHERE user_id=? AND started_at >= DATE('now', '-7 days')
               GROUP BY DATE(started_at)
               ORDER BY day""",
            (user_id,),
        ).fetchall()
        result = [dict(r) for r in rows]

    today = datetime.utcnow().date()
    filled = []
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        found = next((r for r in result if r["day"] == d), None)
        filled.append({"day": d, "count": found["count"] if found else 0})
    return filled


def update_topic_mastery(user_id, domain, topic, is_correct):
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT total_attempted, total_correct FROM topic_mastery WHERE user_id=? AND domain=? AND topic=?",
            (user_id, domain, topic),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE topic_mastery SET total_attempted=?, total_correct=? WHERE user_id=? AND domain=? AND topic=?",
                (row["total_attempted"] + 1, row["total_correct"] + int(is_correct), user_id, domain, topic),
            )
        else:
            conn.execute(
                "INSERT INTO topic_mastery (user_id, domain, topic, total_attempted, total_correct) VALUES (?, ?, ?, 1, ?)",
                (user_id, domain, topic, int(is_correct)),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Diagnostic Baselines
# ---------------------------------------------------------------------------

def init_diagnostic_table():
    """Add diagnostic_baselines table. Call once during setup."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS diagnostic_baselines (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                domain          TEXT NOT NULL,
                topic           TEXT NOT NULL,
                total           INTEGER NOT NULL DEFAULT 0,
                correct         INTEGER NOT NULL DEFAULT 0,
                pct             REAL NOT NULL DEFAULT 0.0,
                taken_at        TEXT NOT NULL,
                UNIQUE(user_id, domain, topic),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.commit()


def save_diagnostic_baseline(user_id, domain, topic, total, correct, pct, taken_at):
    """Save or update a single topic baseline from diagnostic results."""
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO diagnostic_baselines (user_id, domain, topic, total, correct, pct, taken_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, domain, topic) DO UPDATE SET
                total=excluded.total, correct=excluded.correct,
                pct=excluded.pct, taken_at=excluded.taken_at
        """, (user_id, domain, topic, total, correct, pct, taken_at))
        conn.commit()


def get_diagnostic_baseline(user_id):
    """Return all baselines for a user. Returns list of dicts or empty list."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT domain, topic, total, correct, pct, taken_at FROM diagnostic_baselines WHERE user_id=? ORDER BY domain, topic",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def has_diagnostic(user_id):
    """Check if user has already taken the diagnostic."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM diagnostic_baselines WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return row["c"] > 0


def reset_all_progress(user_id):
    with _get_conn() as conn:
        session_ids = [r[0] for r in conn.execute("SELECT id FROM quiz_sessions WHERE user_id=?", (user_id,)).fetchall()]
        if session_ids:
            placeholders = ",".join("?" * len(session_ids))
            conn.execute(f"DELETE FROM answers WHERE user_id=? AND session_id IN ({placeholders})", [user_id] + session_ids)
        conn.execute("DELETE FROM review_queue WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM topic_mastery WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM quiz_sessions WHERE user_id=?", (user_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

def _hash_password(password):
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def _verify_password(password, stored):
    if not stored or ":" not in stored:
        return False
    salt, hashed = stored.split(":", 1)
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == hashed


def generate_access_token():
    """32-char sha256 token, ORDER-portal style (raw hex, exact-match lookup)."""
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()[:32]


def create_user(email=None, password=None, display_name="Student"):
    """Create a REGISTERED user (never anonymous).

    ORDER-faithful auth (FCLE Option 1): every user is a real account with an
    access_token — the dashboard link. `password` is accepted for backward
    compatibility with legacy callers but is no longer the auth mechanism;
    it is stored (hashed) only if provided.
    """
    now = datetime.utcnow().isoformat()
    password_hash = _hash_password(password) if password else None
    token = generate_access_token()
    with _get_conn() as conn:
        if email:
            existing = conn.execute("SELECT id FROM users WHERE email=? AND is_anonymous=0", (email,)).fetchone()
            if existing:
                raise ValueError("Email already registered")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, access_token, display_name, is_anonymous, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (email, password_hash, token, display_name, now),
        )
        conn.commit()
        return get_user(cur.lastrowid)


def get_user_by_token(token):
    """Look up a REGISTERED user by access_token (dashboard link login)."""
    if not token:
        return None
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE access_token=? AND is_anonymous=0", (token,)
        ).fetchone()
        return dict(row) if row else None


def get_user(user_id):
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email):
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None


def verify_login(email, password):
    user = get_user_by_email(email)
    if not user or user.get("is_anonymous") or not user.get("password_hash"):
        return None
    if _verify_password(password, user["password_hash"]):
        return user
    return None


def update_user(user_id, **fields):
    allowed = {"display_name", "exam_date", "target_score", "onboarding_done", "exam_type"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_user(user_id)
    sets = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [user_id]
    with _get_conn() as conn:
        conn.execute(f"UPDATE users SET {sets} WHERE id=?", values)
        conn.commit()
    return get_user(user_id)


def get_total_answered(user_id):
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM answers WHERE user_id=?", (user_id,)).fetchone()
        return row["c"] or 0


# ---------------------------------------------------------------------------
# Paywall (per-app plan column — see platform_lib.py, vendored per app)
# ---------------------------------------------------------------------------

def get_plan(user_id):
    """Plan string for a local user row ('free' default)."""
    with _get_conn() as conn:
        row = conn.execute("SELECT plan FROM users WHERE id=?", (user_id,)).fetchone()
        return (row[0] if row and row[0] else "free") if row else "free"


def _et_day_utc_bounds(day=None):
    """UTC datetime bounds for an America/New_York calendar day.
    Returns (start_utc_naive, end_utc_naive) as datetimes."""
    et = ZoneInfo("America/New_York")
    now_et = datetime.now(et)
    if day is None:
        day = now_et.date()
    start_et = datetime(day.year, day.month, day.day, tzinfo=et)
    end_et = start_et + timedelta(days=1)
    return (start_et.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
            end_et.astimezone(ZoneInfo("UTC")).replace(tzinfo=None))


def count_answers_today(user_id):
    """Free-tier daily usage: answers recorded since midnight America/New_York.
    Compares against answered_at in isoformat 'T'-separator storage."""
    start_dt, end_dt = _et_day_utc_bounds()
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S")
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM answers WHERE user_id=? AND answered_at >= ? AND answered_at < ?",
            (user_id, start_str, end_str),
        ).fetchone()
        return row["c"] or 0


# ---------------------------------------------------------------------------
# Spaced Repetition (SM-2 variant)
# ---------------------------------------------------------------------------

def update_review_queue(user_id, question_id, domain, topic, is_correct, confidence):
    now = datetime.utcnow()
    now_iso = now.isoformat()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, interval_days, ease_factor, times_correct FROM review_queue WHERE user_id=? AND question_id=?",
            (user_id, question_id),
        ).fetchone()

        if row:
            qid = row["id"]
            interval = row["interval_days"]
            ease = row["ease_factor"]
            correct_count = row["times_correct"]

            if is_correct:
                correct_count += 1
                if confidence == 3:
                    interval = interval * ease * 1.3
                elif confidence == 2:
                    interval = interval * ease
                else:
                    interval = max(interval, 1.0)
                if correct_count >= 3:
                    ease = min(ease + 0.1, 3.0)
            else:
                correct_count = 0
                ease = max(ease - 0.3, 1.3)
                interval = 0.5 if confidence == 1 else 1.0

            next_review = (now + timedelta(days=interval)).isoformat()
            conn.execute(
                "UPDATE review_queue SET next_review=?, interval_days=?, ease_factor=?, times_correct=?, domain=?, topic=? WHERE id=?",
                (next_review, interval, ease, correct_count, domain, topic, qid),
            )
        else:
            if is_correct and confidence >= 2:
                interval = 2.0 if confidence == 3 else 1.0
                ease = 2.5
            else:
                interval = 0.5 if confidence == 1 else 1.0
                ease = 2.0

            next_review = (now + timedelta(days=interval)).isoformat()
            conn.execute(
                "INSERT INTO review_queue (user_id, question_id, domain, topic, next_review, interval_days, ease_factor, times_correct) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (user_id, question_id, domain, topic, next_review, interval, ease),
            )

        conn.commit()
# ---- Append to db.py: Active Quiz State (SQLite-backed) ----

import json as _json

def init_active_quizzes_table():
    """Create active_quizzes table. Call at app startup."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_quizzes (
                quiz_id     TEXT PRIMARY KEY,
                quiz_data   TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)
        conn.commit()


def save_quiz(quiz_id, quiz_data):
    """Save or update an active quiz session."""
    now = datetime.utcnow().isoformat()
    data_json = _json.dumps(quiz_data, default=str)
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO active_quizzes (quiz_id, quiz_data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(quiz_id) DO UPDATE SET quiz_data=excluded.quiz_data, updated_at=excluded.updated_at",
            (quiz_id, data_json, now),
        )
        conn.commit()


def load_quiz(quiz_id):
    """Load an active quiz session. Returns dict or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT quiz_data FROM active_quizzes WHERE quiz_id=?", (quiz_id,)
        ).fetchone()
        if row:
            return _json.loads(row["quiz_data"])
        return None


def delete_quiz(quiz_id):
    """Remove a completed quiz session."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM active_quizzes WHERE quiz_id=?", (quiz_id,))
        conn.commit()


def cleanup_stale_quizzes(max_age_hours=6):
    """Remove quiz sessions older than max_age_hours. Call periodically."""
    cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
    with _get_conn() as conn:
        conn.execute("DELETE FROM active_quizzes WHERE updated_at < ?", (cutoff,))
        conn.commit()


# ---------------------------------------------------------------------------
# Pilot signup cap (RC #1) — see DEPLOY.md
# ---------------------------------------------------------------------------

def count_registered_users(exclude_emails=()):
    """Count real (registered, non-anonymous) accounts, minus internal emails.

    Anonymous rows (our seeded test users) and internal addresses never consume
    a pilot seat — so the cap reflects actual students.
    """
    excl = [e.strip().lower() for e in exclude_emails if e and e.strip()]
    q = "SELECT COUNT(*) FROM users WHERE is_anonymous=0 AND email IS NOT NULL"
    params = []
    if excl:
        q += " AND lower(email) NOT IN (%s)" % ",".join("?" * len(excl))
        params = excl
    with _get_conn() as conn:
        return conn.execute(q, params).fetchone()[0]


def create_user_capped(email=None, display_name="Student", cap=None, exclude_emails=(), source=None):
    """Race-safe registered-user creation with an optional pilot cap.

    Returns (user, "ok") on success or (None, "full") when the cap is reached.
    Raises ValueError for a duplicate email. The cap check and the INSERT run
    inside one BEGIN IMMEDIATE write lock, so two simultaneous registrations
    cannot both claim the final seat.
    """
    now = datetime.utcnow().isoformat()
    token = generate_access_token()
    excl = [e.strip().lower() for e in exclude_emails if e and e.strip()]
    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if email:
            existing = conn.execute(
                "SELECT id FROM users WHERE email=? AND is_anonymous=0", (email,)
            ).fetchone()
            if existing:
                raise ValueError("Email already registered")
        if cap:
            q = "SELECT COUNT(*) FROM users WHERE is_anonymous=0 AND email IS NOT NULL"
            params = []
            if excl:
                q += " AND lower(email) NOT IN (%s)" % ",".join("?" * len(excl))
                params = excl
            used = conn.execute(q, params).fetchone()[0]
            if used >= cap:
                conn.rollback()
                return None, "full"
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, access_token, display_name, is_anonymous, created_at, signup_source) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (email, None, token, display_name, now, (source or None)),
        )
        conn.commit()
        return get_user(cur.lastrowid), "ok"
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_to_waitlist(email, source="pilot_full"):
    """Add an email to the pilot waitlist. True if newly added, False if already there."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO waitlist (email, source, created_at) VALUES (?, ?, ?)",
            (email, source, now),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()


def list_waitlist():
    """All waitlist entries, oldest first."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT email, source, created_at FROM waitlist ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
