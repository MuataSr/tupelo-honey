"""
app.py — Tupelo Nursing Exam Prep Flask application.

Civic literacy practice for the Florida Civic Literacy Exam.
Four domains: American Democracy, US Constitution, Founding Documents, Landmark Impact.
All data from kb.py (question bank) and db.py (user progress).
"""

import os
import uuid
import random
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import (Flask, render_template, redirect, url_for, request, jsonify, session, flash)
import kb
import tutor_engine
from coach import library as coach_library
import db
import coach.copy as coach_copy
import coach.engine as coach_engine        # Study Coach: deterministic, no model, no network
import coach.repository as coach_repository

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

# App & Config
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(24).hex())

# ---------------------------------------------------------------------------
# Editions
#
# Sabal is OER full stop: ONE free app, no paid tier, no PRO, no upselling.
# There is no edition flag and no hidden paid surface. The AI tutor is an
# optional "bring your own model" capability (see tutor_engine.py) — it is
# neither gated nor sold. Removing the paid tier here by ABSENCE (no routes,
# no templates, no plan fields in the UI) is what keeps this a legit OER.
# ---------------------------------------------------------------------------

# Active quiz state now in SQLite (see db.py)
db.init_active_quizzes_table()

# Schema migrations (users.access_token, plan, etc.) must run on EVERY boot —
# not only under `python3 app.py` __main__ — or gunicorn/wsgi entry points
# serve a DB without the access_token column and signup crashes.
db.init_db()

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

# Auth Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _get_current_user():
    """Resolve the current REGISTERED user (ORDER-portal style).

    Order of resolution:
      1. session['user_id'] — only if that row is a registered user
         (is_anonymous=0). Stale or anonymous ids are dropped.
      2. ?token= query param — validated against users.access_token
         (the dashboard link).
      3. access_token cookie — same validation.

    Never creates anonymous users. A successful token/cookie lookup
    establishes the Flask session so the internal session-based routes
    keep working unchanged.
    """
    user_id = session.get("user_id")
    if user_id:
        user = db.get_user(user_id)
        if user and not user.get("is_anonymous"):
            return user
        session.pop("user_id", None)

    token = request.args.get("token") or request.cookies.get("access_token")
    if token:
        user = db.get_user_by_token(token)
        if user:
            session["user_id"] = user["id"]
            session.permanent = True
            return user
    return None


def _get_current_user_id():
    """Registered user id for this request, or None. Never auto-creates."""
    user = _get_current_user()
    return user["id"] if user else None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if _get_current_user_id() is None:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


# AI Tutor availability — grey the tutor out in the shell when no LLM is wired.
# check_servers() probes two /health endpoints (up to 3s each), so cache it.
_tutor_conn = {"value": False, "ts": 0.0}
_TUTOR_CONN_TTL = 60.0


def _tutor_connected():
    import time
    now = time.time()
    if now - _tutor_conn["ts"] < _TUTOR_CONN_TTL:
        return _tutor_conn["value"]
    value = False
    try:
        s = _tutor.check_servers()  # module-global TutorEngine, defined below
        value = bool(s.get("router")) and bool(s.get("teacher"))
    except Exception:
        value = False
    _tutor_conn["value"] = value
    _tutor_conn["ts"] = now
    return value


@app.context_processor
def inject_globals():
    """Expose the current user and shell state to all templates.

    Sabal is OER full stop: there is no plan, no premium state, and no
    question cap — every student gets everything, always, for free.
    """
    user = _get_current_user()
    return {
        "current_user": user,
        # Focused surfaces render WITHOUT the app shell (sidebar/topbar):
        # auth pages, and the question/answer/results screens of every
        # assessment flow. Dashboard/hub/tutor keep the shell.
        "standalone": request.endpoint in {
            "login", "signup", "registered", "onboarding",
            "quiz_question", "quiz_answer", "quiz_results",
            "diagnostic_question", "diagnostic_answer", "diagnostic_results",
            "stimulus_practice_question", "stimulus_practice_results",
        },
        "standalone_auth": request.endpoint in {"login", "signup", "registered", "onboarding"},
        "tutor_connected": _tutor_connected(),
    }


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

# Domain Registry
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


_DOMAIN_GETTERS = {
    "reading": {
        "id": 1,
        "topics": kb.get_reading_topics,
        "quiz": kb.get_reading_questions,
        "name": "Reading",
        "icon": "📖",
        "color": "#1B3A5C",
    },
    "math": {
        "id": 2,
        "topics": kb.get_math_topics,
        "quiz": kb.get_math_questions,
        "name": "Math",
        "icon": "🔢",
        "color": "#C7862A",
    },
    "science": {
        "id": 3,
        "topics": kb.get_science_topics,
        "quiz": kb.get_science_questions,
        "name": "Science",
        "icon": "🧬",
        "color": "#2A6F97",
    },
    "english-language": {
        "id": 4,
        "topics": kb.get_english_topics,
        "quiz": kb.get_english_questions,
        "name": "English & Language",
        "icon": "✍️",
        "color": "#6B2737",
    },
}


def _get_domain_info(slug):
    return _DOMAIN_GETTERS.get(slug)


def _pretty_domain(slug):
    info = _DOMAIN_GETTERS.get(slug)
    return info["name"] if info else (slug or "Quiz").title()


def _all_domains(user_id):
    domains = []
    for slug, info in _DOMAIN_GETTERS.items():
        readiness = db.get_readiness(user_id, slug) or 0
        domains.append({
            "domain_name": info["name"],
            "slug": slug,
            "readiness_pct": readiness,
            "icon": info["icon"],
            "color": info["color"],
        })
    return domains


def _greeting():
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    elif hour < 17:
        return "Good afternoon"
    else:
        return "Good evening"


def _exam_countdown(exam_date_str):
    if not exam_date_str:
        return None
    try:
        exam = datetime.strptime(exam_date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        diff = (exam - today).days
        return max(0, diff)
    except (ValueError, TypeError):
        return None


def _build_recommendations(user_id):
    recs = []
    for slug, info in _DOMAIN_GETTERS.items():
        readiness = db.get_readiness(user_id, slug) or 0
        if readiness < 60:
            topics = info["topics"]()
            if topics:
                t = random.choice(topics)
                recs.append({
                    "domain": info["name"],
                    "topic": t["name"],
                    "slug": slug,
                    "level": "Building" if readiness < 40 else ("Fair" if readiness < 70 else "Strong"),
                })
    return recs[:5]


def _build_recent_sessions(user_id):
    sessions = db.get_recent_sessions(user_id, 5)
    result = []
    for s in sessions:
        pct = s.get("pct", 0) or 0
        if pct >= 80:
            status = "Strong"
        elif pct >= 60:
            status = "Fair"
        else:
            status = "Building"
        result.append({
            "domain": s.get("domain", "Unknown"),
            "question_count": s.get("num_questions", 0),
            "score": int(pct),
            "date": s.get("finished_at", "")[:10] if s.get("finished_at") else "—",
            "status": status,
        })
    return result


def _format_time(seconds):
    if seconds is None:
        return "0:00"
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


def _readiness_trend(user_id):
    """14-day daily-average readiness for the trend chart.
    Returns [{day: 'MM/DD', pct: int|None}] oldest->newest."""
    sessions = db.get_recent_sessions(user_id, 200)
    by_day = {}
    for s in sessions:
        finished = s.get("finished_at") or ""
        if not finished:
            continue
        day = finished[:10]
        pct = s.get("pct")
        if pct is None:
            continue
        by_day.setdefault(day, []).append(float(pct))
    out = []
    today = datetime.utcnow().date()
    for i in range(13, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        vals = by_day.get(d)
        out.append({
            "day": d[5:],
            "pct": int(round(sum(vals) / len(vals))) if vals else None,
        })
    return out


def _weak_areas(user_id):
    """Weak topics below 70% w/ >=3 attempts across domains."""
    weak = []
    for slug, info in _DOMAIN_GETTERS.items():
        d_stats = db.get_subject_stats(user_id, slug)
        for t in d_stats.get("topics", []):
            if (t.get("total") or 0) >= 3 and (t.get("pct") or 0) < 70:
                weak.append({
                    "name": t.get("topic", "Topic"),
                    "area": info["name"],
                    "pct": int(round(t.get("pct", 0) or 0)),
                    "url": f"/quiz/{slug}",
                })
    weak.sort(key=lambda w: w["pct"])
    return weak[:8]


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

# Routes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


@app.route("/")
def dashboard():
    user = _get_current_user()
    if user is None:
        return render_template("landing.html", src=_signup_source())
    user_id = user["id"]
    stats = db.get_overall_stats(user_id)
    overall_pct = stats.get("overall_readiness", 0) or 0

    domains = _all_domains(user_id)

    for d in domains:
        d_stats = db.get_subject_stats(user_id, d["slug"])
        weak = 0
        for t in d_stats.get("topics", []):
            if (t.get("pct") or 0) < 60:
                weak += 1
        d["weak_count"] = weak

    recommendations = _build_recommendations(user_id)
    recent_sessions = _build_recent_sessions(user_id)
    for s in recent_sessions:
        s["domain_name"] = _pretty_domain(s.get("domain") or "Quiz")

    display_name = user["display_name"] if user else "Student"
    exam_days = _exam_countdown(user.get("exam_date") if user else None)
    total_questions = kb.get_total_questions()

    return render_template("dashboard.html",
        greeting=_greeting(),
        display_name=display_name,
        overall_pct=int(overall_pct),
        overall_readiness=int(overall_pct),
        domains=domains,
        recommendations=recommendations,
        recent_sessions=recent_sessions,
        exam_days=exam_days,
        total_questions=total_questions,
        is_anonymous=user.get("is_anonymous", 1) if user else 1,
        next_action=_next_action(user_id),
        path_steps=_path_steps(user_id),
    )


@app.route("/quiz/<domain_slug>")
@login_required
def quiz_start(domain_slug):
    user_id = session["user_id"]
    if domain_slug == "mixed":
        return quiz_start_mixed()

    info = _get_domain_info(domain_slug)
    if not info:
        return redirect("/")

    count = request.args.get("count", 5, type=int)
    count = min(count, 20)

    questions = info["quiz"](count=count)
    if not questions:
        return redirect("/")

    quiz_id = uuid.uuid4().hex[:12]
    db.save_quiz(quiz_id, {
        "user_id": user_id,
        "domain": domain_slug,
        "questions": questions,
        "current_index": 0,
        "answers": [],
        "started_at": datetime.now().isoformat(),
        "session_id": None,
    })

    return redirect(f"/quiz/{domain_slug}/{quiz_id}/0")


def quiz_start_mixed():
    user_id = session["user_id"]
    count = request.args.get("count", 10, type=int)
    count = min(count, 20)

    questions = kb.get_mixed_quiz_questions(count=count)

    if not questions:
        return redirect("/")

    quiz_id = uuid.uuid4().hex[:12]
    db.save_quiz(quiz_id, {
        "user_id": user_id,
        "domain": "mixed",
        "questions": questions,
        "current_index": 0,
        "answers": [],
        "started_at": datetime.now().isoformat(),
        "session_id": None,
    })

    return redirect(f"/quiz/mixed/{quiz_id}/0")


@app.route("/quiz/<domain_slug>/<quiz_id>/<int:q_index>")
@login_required
def quiz_question(domain_slug, quiz_id, q_index):
    quiz = db.load_quiz(quiz_id)
    if not quiz:
        return redirect("/")

    questions = quiz["questions"]
    if q_index < 0 or q_index >= len(questions):
        return redirect("/")

    question = questions[q_index]

    domain_name = "Mixed Review"
    if domain_slug != "mixed":
        info = _get_domain_info(domain_slug)
        domain_name = info["name"] if info else domain_slug

    return render_template("quiz.html",
        question=question,
        current_q=q_index + 1,
        total_q=len(questions),
        domain_name=domain_name,
        domain_slug=domain_slug,
        quiz_id=quiz_id,
    )


@app.route("/quiz/<domain_slug>/<quiz_id>/<int:q_index>/answer", methods=["POST"])
@login_required
def quiz_answer(domain_slug, quiz_id, q_index):
    quiz = db.load_quiz(quiz_id)
    if not quiz:
        return redirect("/")

    user_id = quiz.get("user_id", session["user_id"])
    questions = quiz["questions"]
    if q_index < 0 or q_index >= len(questions):
        return redirect("/")

    question = questions[q_index]
    selected = request.form.get("selected", "")
    time_elapsed = request.form.get("time_elapsed", 0, type=float)
    confidence = request.form.get("confidence", None, type=int)

    correct_answer = question.get("correct_answer", "")
    is_correct = str(selected).strip() == str(correct_answer).strip()

    answer = {
        "question_id": question.get("id", q_index),
        "question_text": question.get("question_text", ""),
        "selected": selected,
        "correct": correct_answer,
        "is_correct": is_correct,
        "time_elapsed": time_elapsed,
        "confidence": confidence,
        "topic": question.get("topic", ""),
    }
    quiz["answers"].append(answer)

    if quiz["session_id"] is None:
        quiz["session_id"] = db.create_session(
            user_id=user_id,
            domain=quiz["domain"],
            num_questions=len(questions),
        )

    db.record_answer(
        user_id=user_id,
        session_id=quiz["session_id"],
        question_id=question.get("id", q_index),
        question_text=question.get("question_text", ""),
        selected=selected,
        correct=correct_answer,
        is_correct=is_correct,
        time_elapsed=int(time_elapsed),
        confidence=confidence,
    )

    topic = question.get("topic", "")
    if topic:
        db.update_topic_mastery(user_id, quiz["domain"], topic, is_correct)

    if confidence is not None:
        db.update_review_queue(
            user_id=user_id,
            question_id=question.get("id", q_index),
            domain=quiz["domain"],
            topic=topic,
            is_correct=is_correct,
            confidence=confidence,
        )

    # Persist quiz state to SQLite
    db.save_quiz(quiz_id, quiz)

    next_index = q_index + 1
    explanation = question.get("explanation", "")
    wrong_explanations = question.get("wrong_explanations", [])
    wrong_answers = question.get("wrong_answers", [])
    # Build a map: wrong_answer -> wrong_explanation
    wrong_explanation_map = {}
    if wrong_explanations and wrong_answers:
        for i, wa in enumerate(wrong_answers):
            if i < len(wrong_explanations):
                wrong_explanation_map[wa] = wrong_explanations[i]
    # Also try building from options: anything that's not correct_answer
    if not wrong_explanation_map and wrong_explanations:
        options = question.get("options", [])
        idx = 0
        for opt in options:
            if opt != correct_answer and idx < len(wrong_explanations):
                wrong_explanation_map[opt] = wrong_explanations[idx]
                idx += 1

    feedback_mode = "quiz"
    if confidence == 1:
        feedback_mode = "teach"
    elif confidence == 2:
        feedback_mode = "hint"

    domain_name = "Mixed Review"
    if domain_slug != "mixed":
        info = _get_domain_info(domain_slug)
        domain_name = info["name"] if info else domain_slug

    # --- why the student picked what they picked -------------------------------
    # The page already explains the correct option and why each wrong option fails.
    # Both are option-centric: they say what is true, never why this student chose
    # what they chose. This adds that layer, reusing the coach's own diagnosis so the
    # two surfaces cannot drift apart. It is additive: a missing diagnosis is a worse
    # page, not a broken one, so the failure is logged rather than raised.
    coach_feedback = None
    try:
        _library = coach_library.load(_COACH_CONTENT_DB)
        # domain_slug is a slug ("american-democracy"), not a domain id. Mixed Review
        # has no domain of its own, so leave it None and let the question resolve it.
        _domain_id = (_DOMAIN_GETTERS.get(domain_slug) or {}).get("id")
        _directive = coach_library.directive_for(
            _library,
            {"question_id": question.get("id", q_index), "domain": _domain_id,
             "topic": topic, "is_correct": is_correct, "confidence": confidence,
             "selected_answer": selected},
            question, domain=_domain_id)
        coach_feedback = coach_library.feedback_view(_directive)
    except Exception as exc:      # noqa: BLE001 - additive layer; see note above
        app.logger.warning("coach feedback unavailable: %s", exc)

    render_kwargs = dict(
        question=question,
        current_q=q_index + 1,
        total_q=len(questions),
        domain_name=domain_name,
        domain_slug=domain_slug,
        quiz_id=quiz_id,
        feedback=True,
        is_correct=is_correct,
        selected=selected,
        correct_answer=correct_answer,
        explanation=explanation,
        wrong_explanation_map=wrong_explanation_map,
        feedback_mode=feedback_mode,
        coach_feedback=coach_feedback,
    )

    if next_index < len(questions):
        render_kwargs["next_url"] = f"/quiz/{domain_slug}/{quiz_id}/{next_index}"
    else:
        correct_count = sum(1 for a in quiz["answers"] if a["is_correct"])
        total = len(quiz["answers"])
        pct = int((correct_count / total * 100) if total else 0)
        db.finish_session(quiz["session_id"], correct_count, total, pct)
        render_kwargs["next_url"] = f"/results/{domain_slug}/{quiz_id}"

    return render_template("quiz.html", **render_kwargs)


@app.route("/results/<domain_slug>/<quiz_id>")
@login_required
def quiz_results(domain_slug, quiz_id):
    quiz = db.load_quiz(quiz_id)
    if not quiz:
        return redirect("/")

    answers = quiz["answers"]
    questions = quiz["questions"]

    correct_count = sum(1 for a in answers if a["is_correct"])
    total = len(answers)
    pct = int((correct_count / total * 100) if total else 0)
    elapsed = sum(a.get("time_elapsed", 0) for a in answers)

    best_streak = 0
    current_streak = 0
    for a in answers:
        if a["is_correct"]:
            current_streak += 1
            best_streak = max(best_streak, current_streak)
        else:
            current_streak = 0

    topic_map = {}
    for a in answers:
        topic = a.get("topic", "General")
        if topic not in topic_map:
            topic_map[topic] = {"correct": 0, "total": 0}
        topic_map[topic]["total"] += 1
        if a["is_correct"]:
            topic_map[topic]["correct"] += 1

    topic_breakdown = [
        {"topic": t, "correct": v["correct"], "total": v["total"]}
        for t, v in topic_map.items()
    ]

    mistakes = [
        {
            "question": a["question_text"],
            "user_answer": a["selected"],
            "correct_answer": a["correct"],
            "explanation": next(
                (q.get("explanation", "") for q in questions if q.get("question_text") == a["question_text"]),
                "",
            ),
        }
        for a in answers if not a["is_correct"]
    ]

    domain_name = "Mixed Review"
    if domain_slug != "mixed":
        info = _get_domain_info(domain_slug)
        domain_name = info["name"] if info else domain_slug

    db.delete_quiz(quiz_id)

    return render_template("results.html",
        score=correct_count,
        total=total,
        pct=pct,
        elapsed_time=_format_time(elapsed),
        accuracy=pct,
        best_streak=best_streak,
        topic_breakdown=topic_breakdown,
        mistakes=mistakes,
        domain_slug=domain_slug,
        domain_name=domain_name,
    )


@app.route("/stats")
@login_required
def stats():
    user_id = session["user_id"]
    overall_stats = db.get_overall_stats(user_id)
    overall_readiness = int(overall_stats.get("overall_readiness", 0) or 0)

    domains = []
    for slug in _DOMAIN_GETTERS:
        info = _DOMAIN_GETTERS[slug]
        d_stats = db.get_subject_stats(user_id, slug)
        topics = info["topics"]()

        db_topics = {t["topic"]: t for t in d_stats.get("topics", [])}
        strong = 0
        for t in topics:
            db_t = db_topics.get(t["name"]) or db_topics.get(t.get("slug", ""))
            if db_t and (db_t.get("pct") or 0) >= 80:
                strong += 1

        domains.append({
            "name": info["name"],
            "slug": slug,
            "icon": info["icon"],
            "readiness_pct": int(d_stats.get("readiness_pct", 0) or 0),
            "strong_topics": strong,
            "total_topics": len(topics),
        })

    recent = db.get_recent_sessions(user_id, 10)
    recent_quizzes = []
    for s in recent:
        recent_quizzes.append({
            "date": s.get("finished_at", "")[:10] if s.get("finished_at") else "—",
            "domain_name": s.get("domain", "Unknown").title(),
            "domain_slug": s.get("domain", ""),
            "score": int(s.get("pct", 0) or 0),
            "total_questions": s.get("num_questions", 0),
        })

    weekly = db.get_weekly_activity(user_id)

    current_streak = 0
    today = datetime.utcnow().date()
    check_date = today
    activity_days = {w.get("day", "") for w in weekly}
    while True:
        if check_date.isoformat() in activity_days:
            current_streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    return render_template("stats.html",
        overall_readiness=overall_readiness,
        domains=domains,
        recent_quizzes=recent_quizzes,
        weekly_activity=weekly,
        current_streak=current_streak,
        trend=_readiness_trend(user_id),
        weak=_weak_areas(user_id),
        active_nav="stats",
    )


@app.route("/settings")
@login_required
def settings():
    _q_counts = kb.get_question_counts()
    _q_total = sum(c["total"] for c in _q_counts.values())
    return render_template("settings.html",
        user=_get_current_user(),
        version="0.1.0 MVP",
        total_questions=f"{_q_total:,}",
        active_nav="settings",
    )


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

# Diagnostic (Pre-Test)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _build_diagnostic_questions():
    """Build 20 diagnostic questions: 5 per domain, mixed difficulty."""
    questions = []
    for slug, info in _DOMAIN_GETTERS.items():
        qs = info["quiz"](count=5)
        for q in qs:
            q["_domain_slug"] = slug
            q["_domain_name"] = info["name"]
            questions.append(q)
    random.shuffle(questions)
    return questions


@app.route("/diagnostic", methods=["GET", "POST"])
@login_required
def diagnostic():
    user_id = session["user_id"]
    already = db.has_diagnostic(user_id)

    if request.method == "POST":
        # Start diagnostic quiz
        questions = _build_diagnostic_questions()
        quiz_id = uuid.uuid4().hex[:12]
        db.save_quiz(quiz_id, {
            "questions": questions,
            "answers": [],
            "started_at": datetime.utcnow().isoformat(),
            "is_diagnostic": True,
        })
        return redirect(f"/diagnostic/{quiz_id}/0")

    return render_template("diagnostic.html",
        user=_get_current_user(),
        already_taken=already,
        active_nav="diagnostic",
    )


@app.route("/diagnostic/<quiz_id>/<int:q_index>", methods=["GET"])
@login_required
def diagnostic_question(quiz_id, q_index):
    quiz = db.load_quiz(quiz_id)
    if not quiz or not quiz.get("is_diagnostic"):
        flash("Diagnostic session not found.", "error")
        return redirect("/diagnostic")

    questions = quiz["questions"]
    if q_index >= len(questions):
        return redirect(f"/diagnostic/results/{quiz_id}")

    q = questions[q_index]
    q["index"] = q_index
    q["total"] = len(questions)
    q["options"] = q.get("options", [])

    return render_template("diagnostic_quiz.html",
        question=q,
        quiz_id=quiz_id,
        q_index=q_index,
        total=len(questions),
        active_nav="diagnostic",
    )


@app.route("/diagnostic/<quiz_id>/<int:q_index>/answer", methods=["POST"])
@login_required
def diagnostic_answer(quiz_id, q_index):
    quiz = db.load_quiz(quiz_id)
    if not quiz or not quiz.get("is_diagnostic"):
        return redirect("/diagnostic")

    questions = quiz["questions"]
    if q_index >= len(questions):
        return redirect(f"/diagnostic/results/{quiz_id}")

    q = questions[q_index]
    selected = request.form.get("selected", "")
    is_correct = str(selected).strip() == str(q.get("correct_answer", "")).strip()
    quiz["answers"].append({
        "question_id": q["id"],
        "question_text": q["question_text"],
        "selected": selected,
        "correct": q.get("correct_answer", ""),
        "is_correct": is_correct,
        "domain": q["_domain_slug"],
        "domain_name": q["_domain_name"],
        "topic": q.get("topic", ""),
    })

    # Persist — without this, answers are lost on redirect and the
    # results page loads an empty-answers quiz (500: study_order[0]).
    db.save_quiz(quiz_id, quiz)

    next_index = q_index + 1
    if next_index >= len(questions):
        return redirect(f"/diagnostic/results/{quiz_id}")
    return redirect(f"/diagnostic/{quiz_id}/{next_index}")


@app.route("/diagnostic/results/<quiz_id>")
@login_required
def diagnostic_results(quiz_id):
    quiz = db.load_quiz(quiz_id)
    if not quiz or not quiz.get("is_diagnostic"):
        flash("Diagnostic session not found.", "error")
        return redirect("/diagnostic")

    answers = quiz["answers"]
    taken_at = quiz["started_at"]
    user_id = session["user_id"]

    # Build per-domain and per-topic results
    domain_results = {}
    topic_results = {}

    for a in answers:
        dom = a["domain"]
        dom_name = a["domain_name"]
        topic = a["topic"]

        if dom not in domain_results:
            domain_results[dom] = {"name": dom_name, "slug": dom, "total": 0, "correct": 0}
        domain_results[dom]["total"] += 1
        if a["is_correct"]:
            domain_results[dom]["correct"] += 1

        key = f"{dom}|{topic}"
        if key not in topic_results:
            topic_results[key] = {
                "domain": dom, "domain_name": dom_name, "topic": topic,
                "total": 0, "correct": 0,
            }
        topic_results[key]["total"] += 1
        if a["is_correct"]:
            topic_results[key]["correct"] += 1

    # Calculate percentages and sort
    for d in domain_results.values():
        d["pct"] = round(d["correct"] / d["total"] * 100, 1) if d["total"] > 0 else 0

    for t in topic_results.values():
        t["pct"] = round(t["correct"] / t["total"] * 100, 1) if t["total"] > 0 else 0

    # Sort domains: weakest first (study order)
    sorted_domains = sorted(domain_results.values(), key=lambda x: x["pct"])

    # Sort topics: weakest first
    sorted_topics = sorted(topic_results.values(), key=lambda x: x["pct"])

    # Identify strengths and weaknesses
    strengths = [d for d in domain_results.values() if d["pct"] >= 80]
    weaknesses = [d for d in domain_results.values() if d["pct"] < 60]
    middle = [d for d in domain_results.values() if 60 <= d["pct"] < 80]

    # Save baselines to DB
    for key, t in topic_results.items():
        db.save_diagnostic_baseline(
            user_id, t["domain"], t["topic"],
            t["total"], t["correct"], t["pct"], taken_at,
        )

    # Overall score
    total_q = len(answers)
    total_correct = sum(1 for a in answers if a["is_correct"])
    overall_pct = round(total_correct / total_q * 100, 1) if total_q > 0 else 0

    # Clean up active quiz
    db.delete_quiz(quiz_id)

    return render_template("diagnostic_results.html",
        overall_pct=overall_pct,
        total_correct=total_correct,
        total_questions=total_q,
        domain_results=sorted_domains,
        topic_results=sorted_topics,
        strengths=strengths,
        weaknesses=weaknesses,
        middle=middle,
        study_order=sorted_domains,
        active_nav="diagnostic",
    )


@app.route("/settings/exam-date", methods=["POST"])
@login_required
def settings_exam_date():
    user_id = session["user_id"]
    exam_date = request.form.get("exam_date", "").strip() or None
    db.update_user(user_id, exam_date=exam_date)
    flash("Exam date saved.", "success")
    return redirect("/settings")


@app.route("/settings/reset", methods=["POST"])
@login_required
def settings_reset():
    user_id = session["user_id"]
    db.reset_all_progress(user_id)
    flash("All progress has been reset.", "success")
    return redirect("/settings")


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

# Auth Routes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Pilot signup cap (RC #1)
# Env: PILOT_SIGNUP_CAP, PILOT_INTERNAL_EMAILS, PILOT_BYPASS_KEY, PILOT_ADMIN_KEY
# See DEPLOY.md. Cap 0/absent = uncapped.
# ---------------------------------------------------------------------------

def _signup_source():
    """Channel attribution for partner links (?src=phsc). Lowercase, safe charset."""
    raw = (request.form.get("src") or request.args.get("src") or "").strip().lower()
    safe = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")[:32]
    return safe or None


def _pilot_cap():
    """Pilot seat cap (0 = uncapped)."""
    try:
        return int((os.environ.get("PILOT_SIGNUP_CAP") or "0").strip() or 0)
    except (TypeError, ValueError):
        return 0


def _pilot_internal_emails():
    """Addresses that never consume a pilot seat (founder + our test accounts)."""
    raw = os.environ.get("PILOT_INTERNAL_EMAILS") or ""
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def _pilot_bypass_ok():
    """True when a valid bypass key is present, so we can register past the cap."""
    key = (os.environ.get("PILOT_BYPASS_KEY") or "").strip()
    if not key:
        return False
    supplied = (request.args.get("bypass") or request.form.get("bypass") or "").strip()
    return supplied == key


def _pilot_seats_used():
    return db.count_registered_users(_pilot_internal_emails())


def _pilot_is_full():
    cap = _pilot_cap()
    return bool(cap) and _pilot_seats_used() >= cap


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        # Honeypot: the "website" field is off-screen and only a bot fills it.
        # Silently accept-and-drop so the bot believes it succeeded, and no
        # account (or pilot seat) is ever created for it.
        if (request.form.get("website") or "").strip():
            app.logger.warning("signup honeypot triggered (trap field filled)")
            return redirect("/")

        bypass = _pilot_bypass_ok()

        # Pilot cap: refuse registration once every seat is taken. Enforced
        # server-side, so a direct POST cannot slip past a hidden form.
        if _pilot_is_full() and not bypass:
            return render_template("signup.html", pilot_full=True, pilot_cap=_pilot_cap())

        email = request.form.get("email", "").strip().lower()
        display_name = request.form.get("display_name", "").strip() or "Student"

        if not email or "@" not in email or "." not in email:
            flash("A valid email is required.", "error")
            return render_template("signup.html")
        if len(display_name) > 60:
            flash("Display name is too long.", "error")
            return render_template("signup.html")

        try:
            # Race-safe: the seat check and the INSERT happen under one write
            # lock, so two simultaneous registrations cannot both take the last seat.
            user, status = db.create_user_capped(
                email=email,
                display_name=display_name,
                cap=None if bypass else (_pilot_cap() or None),
                exclude_emails=_pilot_internal_emails(),
                source=_signup_source(),
            )
            if status == "full":
                return render_template("signup.html", pilot_full=True, pilot_cap=_pilot_cap())
            if not user:
                flash("Account could not be created. Please try again.", "error")
                return render_template("signup.html")
            # New users land in onboarding first (onboarding_done defaults to 0):
            # set exam date + target score, see the path, then start the loop.
            session["user_id"] = user["id"]
            session.permanent = True
            # ORDER-faithful: registration completes → user is issued their
            # personal dashboard link automatically and taken to the page
            # that hands it to them (no password anywhere in the flow).
            return redirect("/registered")
        except ValueError as e:
            flash(str(e), "error")
            return render_template("signup.html")

    if _pilot_is_full() and not _pilot_bypass_ok():
        return render_template("signup.html", pilot_full=True, pilot_cap=_pilot_cap(),
                               src=_signup_source())
    return render_template("signup.html", src=_signup_source())


@app.route("/waitlist", methods=["POST"])
def waitlist_join():
    """Pilot-full fallback: collect an email for the next cohort (manual outreach)."""
    if (request.form.get("website") or "").strip():
        app.logger.warning("waitlist honeypot triggered (trap field filled)")
        return redirect("/")
    email = (request.form.get("email") or "").strip().lower()
    if not email or "@" not in email or "." not in email:
        flash("Please enter a valid email.", "error")
        return render_template("signup.html", pilot_full=True, pilot_cap=_pilot_cap())
    if db.get_user_by_email(email):
        return render_template("signup.html", pilot_full=True, pilot_cap=_pilot_cap(),
                               waitlist_existing=True)
    added = db.add_to_waitlist(email, source=(_signup_source() or "pilot_full"))
    return render_template("signup.html", pilot_full=True, pilot_cap=_pilot_cap(),
                           waitlist_done=True, waitlist_email=email, waitlist_dupe=not added)


@app.route("/admin/waitlist")
def admin_waitlist():
    """Read-only pilot waitlist for manual outreach (key-protected, unlinked)."""
    key = (os.environ.get("PILOT_ADMIN_KEY") or "").strip()
    if not key or (request.args.get("key") or "") != key:
        return "Not found", 404
    rows = db.list_waitlist()
    if (request.args.get("format") or "") == "csv":
        out = "email,source,created_at\n" + "".join(
            "%s,%s,%s\n" % (r["email"], r["source"] or "", r["created_at"]) for r in rows)
        return out, 200, {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "attachment; filename=sabal-pilot-waitlist.csv",
        }
    lines = "\n".join("%s  (%s)" % (r["email"], (r["created_at"] or "")[:19]) for r in rows) or "(empty)"
    html = (
        "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<h2>Sabal pilot waitlist &mdash; %d</h2>"
        "<p>Seats used: %d of %d</p><pre>%s</pre>"
        "<p><a href='?key=%s&amp;format=csv'>Download CSV</a></p>"
    ) % (len(rows), _pilot_seats_used(), _pilot_cap(), lines, key)
    return html


def _try_email_dashboard_link(user, link):
    """Email the user their dashboard link via the Resend API (HTTPS).

    The droplet blocks outbound SMTP (25/465/587), so delivery goes over HTTPS via
    Resend. Returns False when no API key is set or a send fails, so the on-screen
    link remains the fallback. Never pretend an email was sent.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return False
    try:
        import json
        import urllib.request
        recipient = (user or {}).get("email")
        sender = os.environ.get("RESEND_FROM") or "Tupelo Nursing Exam Prep <muata@mu2.solutions>"
        if not sender or not recipient:
            return False
        body = (
            f"Hi {(user or {}).get('display_name') or 'Student'},\n\n"
            f"Your Sabal dashboard link:\n\n{link}\n\n"
            f"Open it and you'll land straight on your dashboard. Keep it safe — "
            f"it's how you log in.\n\n— Tupelo Nursing Exam Prep (Mu2 Solutions)"
        )
        payload = {
            "from": sender,
            "to": [recipient],
            "subject": "Your Sabal dashboard link",
            "text": body,
        }
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "tupelo/1.0",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception:
        return False


@app.route("/registered")
@login_required
def registered():
    """Post-registration / returning-user handoff: show the user their
    personal dashboard link (the link IS the login, ORDER-portal style)."""
    user = _get_current_user()
    if not user or not user.get("access_token"):
        return redirect(url_for("login"))
    link = request.url_root.rstrip("/") + "/?token=" + user["access_token"]
    nxt = request.args.get("next") or "/"
    email_sent = _try_email_dashboard_link(user, link)
    return render_template("registered.html", user=user, dashboard_link=link,
                           returning=request.args.get("r") == "1", next=nxt,
                           email_sent=email_sent)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not email:
            flash("Enter your email to get your dashboard link.", "error")
            return render_template("login.html")

        user = db.get_user_by_email(email)
        if not user or user.get("is_anonymous"):
            flash("No account found with that email — create one below.", "error")
            return render_template("login.html")

        # No password: the account's access link is the credential. Establish
        # the session and take them to the page that re-issues their link.
        session["user_id"] = user["id"]
        session.permanent = True
        nxt = request.args.get("next") or ""
        return redirect("/registered?r=1" + (f"&next={nxt}" if nxt else ""))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out. See you next time!", "success")
    return redirect("/login")


# ---------------------------------------------------------------------------
# Study Coach
#
# The whole engine is pure Python in the `coach` package - no model, no network,
# no inference. This route only loads state, calls the engine and renders.
#
# The plan is cached per user per day: it is a pure function of that day's data,
# so recomputing it on every request buys nothing, and the authenticated
# dashboard's per-domain stats loop is already the measured throughput ceiling
# on the droplet. `?refresh=1` busts the entry.
# ---------------------------------------------------------------------------
_COACH_CACHE = {}
_COACH_CACHE_MAX = 500
_coach_lock = threading.Lock()
_COACH_CONTENT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tupelo.db")
_DOMAIN_ID_TO_SLUG = {info["id"]: slug for slug, info in _DOMAIN_GETTERS.items()}


def _coach_plan(user_id, refresh=False):
    """Build (or reuse today's) plan for a user."""
    now = datetime.now(timezone.utc)
    key = (user_id, now.date().isoformat())
    if not refresh:
        with _coach_lock:
            cached = _COACH_CACHE.get(key)
        if cached is not None:
            return cached
    state = coach_repository.load_state(user_id, _COACH_CONTENT_DB, db.DB_PATH, now=now)
    plan = coach_engine.build(state)
    with _coach_lock:
        if len(_COACH_CACHE) >= _COACH_CACHE_MAX:
            _COACH_CACHE.clear()
        _COACH_CACHE[key] = plan
    return plan


def _next_action(user_id):
    """The single 'what should I do right now' step, derived from the coach plan."""
    # Entry point: no diagnostic yet → start there before anything else.
    if not db.has_diagnostic(user_id):
        return {
            "eyebrow": "Start here",
            "title": "Take the 20-question diagnostic",
            "detail": "Find your starting point across all four subject areas — then we build a plan around your weak spots.",
            "cta_text": "Start the diagnostic",
            "cta_url": "/diagnostic",
            "kind": "diagnostic",
        }
    plan = _coach_plan(user_id)
    slug = _DOMAIN_ID_TO_SLUG.get(plan.focus_domain) or "mixed"
    block = plan.blocks[0] if plan.blocks else None
    if block is not None:
        title = block.text
        detail = ("Focus: " + block.topic) if block.topic else "Most-missed first, based on your latest results."
        kind = block.kind
    else:
        title = plan.title
        detail = plan.blurb
        kind = "review"
    return {
        "eyebrow": "Your next step",
        "title": title,
        "detail": detail,
        "cta_text": "Start now",
        "cta_url": "/quiz/" + slug,
        "kind": kind,
    }


def _path_steps(user_id):
    """Four-step loop (Diagnose → Practice → Review → Re-check) with the
    student's current position, for the always-visible path indicator."""
    labels = ["Diagnose", "Practice", "Review", "Re-check"]
    if not db.has_diagnostic(user_id):
        current = 0
    else:
        plan = _coach_plan(user_id)
        kind = plan.blocks[0].kind if plan.blocks else "new"
        if kind == "timed":
            current = 3
        elif kind == "review":
            current = 2
        else:
            current = 1
    return [
        {"label": label, "state": ("done" if i < current else "current" if i == current else "upcoming")}
        for i, label in enumerate(labels)
    ]


def _tutor_chat_history(user_id):
    """Most recent tutor chat messages (chronological, oldest first)."""
    try:
        import sqlite3 as _sq
        _c = _sq.connect("data/user_progress.db")
        _c.row_factory = _sq.Row
        _rows = _c.execute(
            "SELECT role, content, domain, created_at FROM tutor_messages WHERE user_id=? ORDER BY id DESC LIMIT 50",
            (user_id,),
        ).fetchall()
        _c.close()
        return [{"role": r["role"], "content": r["content"], "domain": r["domain"], "time": r["created_at"]} for r in reversed(_rows)]
    except Exception:
        return []


@app.route("/coach")
@login_required
def coach():
    """The Coach hub: today's plan, readiness, reading, standards, and tutor."""
    user_id = session["user_id"]
    plan = _coach_plan(user_id, refresh=request.args.get("refresh") == "1")

    slug = _DOMAIN_ID_TO_SLUG.get(plan.focus_domain)

    report_absent = ""
    if plan.reporting is None and plan.has_data:
        report_absent = coach_copy.benchmark_report_absent(plan.focus_domain)

    return render_template(
        "coach.html",
        plan=plan,
        drill_slug=slug,
        readiness_pct=int(round(plan.readiness * 100)),
        empty_text=coach_copy.plan_empty(),
        widening_text=coach_copy.readiness_widening(),
        no_data_text=coach_copy.readiness_unknown(),
        report_title=coach_copy.benchmark_report_title(),
        report_absent=report_absent,
        chat_messages=_tutor_chat_history(user_id),
    )


@app.route("/account")
@login_required
def account():
    """Student account portal — one free OER app, no plan and no cap."""
    user_id = session["user_id"]
    user = _get_current_user() or {}
    stats = db.get_overall_stats(user_id)
    total = db.get_total_answered(user_id)

    areas = [{"name": _pretty_domain(d.get("name") or d.get("slug") or ""),
              "pct": int(d["readiness_pct"])}
             for d in stats.get("domains", [])]
    recent = [{"name": _pretty_domain(s.get("domain") or "Quiz"),
               "score": s.get("score", 0), "date": s.get("date", "—"),
               "status": s.get("status", "Building")}
              for s in _build_recent_sessions(user_id)]
    created = user.get("created_at", "") or ""

    return render_template("portal.html",
        app_name="Tupelo Nursing Exam Prep",
        app_slug="tupelo",
        total_answered=total,
        overall_pct=int(stats.get("overall_readiness", 0) or 0),
        exam_days=_exam_countdown(user.get("exam_date") if user else None),
        member_since=created[:10] if created else None,
        areas=areas,
        chips=[{"label": "Total answered", "value": total}],
        recent_sessions=recent,
        active_nav="account",
    )


@app.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    user_id = session["user_id"]
    user = _get_current_user()

    if user and user.get("onboarding_done"):
        return redirect("/")

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip() or "Student"
        exam_type = request.form.get("exam_type", "teas").strip().lower()
        if exam_type not in ("teas", "hesi", "both"):
            exam_type = "teas"
        exam_date = request.form.get("exam_date", "").strip() or None
        target_score = request.form.get("target_score", 80, type=int)
        target_score = max(0, min(100, target_score))

        db.update_user(user_id,
            display_name=display_name,
            exam_type=exam_type,
            exam_date=exam_date,
            target_score=target_score,
            onboarding_done=1,
        )
        flash("Profile saved! Let's start studying.", "success")
        return redirect("/")

    return render_template("onboarding.html", user=user)


@app.route("/onboarding/skip")
@login_required
def onboarding_skip():
    """Skip personalization for now — mark onboarding done and continue."""
    db.update_user(session["user_id"], onboarding_done=1)
    return redirect("/")


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

# Stimulus Literacy Training
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


@app.route("/stimulus")
@login_required
def stimulus_hub():
    """Hub page: pick domain or do mixed stimulus practice."""
    domains = kb.get_domains()
    domain_data = []
    for d in domains:
        stim_count = kb.get_stimulus_questions(domain_id=d["id"], count=999)
        domain_data.append({
            "id": d["id"],
            "name": d["name"],
            "slug": d["name"].lower().replace(" ", "-"),
            "stimulus_count": len(stim_count),
        })
    total_stim = sum(dd["stimulus_count"] for dd in domain_data)
    total_questions = kb.get_total_questions()

    return render_template("stimulus_hub.html",
        domains=domain_data,
        total_stimulus=total_stim,
        total_questions=total_questions,
        active_nav="stimulus",
    )


@app.route("/stimulus/practice", methods=["GET", "POST"])
@app.route("/stimulus/practice/<int:domain_id>", methods=["GET", "POST"])
@login_required
def stimulus_practice(domain_id=None):
    """Practice reading stimulus passages with guided annotation steps."""
    if request.method == "POST":
        # Start a new practice session
        count = min(int(request.form.get("count", 5)), 20)
        questions = kb.get_stimulus_questions(domain_id=domain_id, count=count)
        if not questions:
            flash("No stimulus questions available for this selection.", "error")
            return redirect(f"/stimulus")

        quiz_id = uuid.uuid4().hex[:12]
        db.save_quiz(quiz_id, {
            "questions": questions,
            "answers": [],
            "started_at": datetime.utcnow().isoformat(),
            "is_stimulus": True,
            "domain_id": domain_id,
        })
        return redirect(f"/stimulus/practice/{quiz_id}/0")

    domain_name = None
    if domain_id:
        domains = kb.get_domains()
        domain_name = next((d["name"] for d in domains if d["id"] == domain_id), "Unknown")

    return render_template("stimulus_practice_setup.html",
        domain_id=domain_id,
        domain_name=domain_name,
        active_nav="stimulus",
    )


@app.route("/stimulus/practice/<quiz_id>/<int:q_index>", methods=["GET", "POST"])
@login_required
def stimulus_practice_question(quiz_id, q_index):
    """Show a stimulus question with guided annotation workflow."""
    quiz = db.load_quiz(quiz_id)
    if not quiz or not quiz.get("is_stimulus"):
        flash("Practice session not found.", "error")
        return redirect("/stimulus")

    questions = quiz["questions"]
    if q_index >= len(questions):
        return redirect(f"/stimulus/practice/results/{quiz_id}")

    q = questions[q_index]

    # Parse options
    wrong_answers = q.get("wrong_answers", "[]")
    if isinstance(wrong_answers, str):
        wrong_answers = eval(wrong_answers) if wrong_answers.startswith("[") else wrong_answers.split("|")
    correct = q.get("correct_answer", "")
    all_options = wrong_answers + [correct]
    random.shuffle(all_options)

    # Step management
    step = request.form.get("step", request.args.get("step", "read"))
    annotation = request.form.get("annotation", "")
    guess = request.form.get("guess", "")

    if request.method == "POST":
        new_step = request.form.get("next_step", "")
        if new_step:
            step = new_step
            if new_step == "answer":
                annotation = request.form.get("annotation", "")
            elif new_step == "results":
                # Save answer
                selected = request.form.get("selected", "")
                is_correct = selected == correct
                quiz["answers"].append({
                    "question_id": q["id"],
                    "question_text": q["question"],
                    "stimulus": q["stimulus"],
                    "selected": selected,
                    "correct": correct,
                    "is_correct": is_correct,
                    "annotation": annotation,
                    "guess": guess,
                    "topic": q.get("topic", ""),
                    "domain_id": q.get("fcle_domain", ""),
                })
                # Persist stimulus state to SQLite
                db.save_quiz(quiz_id, quiz)
                next_idx = q_index + 1
                if next_idx >= len(questions):
                    return redirect(f"/stimulus/practice/results/{quiz_id}")
                return redirect(f"/stimulus/practice/{quiz_id}/{next_idx}")

    return render_template("stimulus_practice_question.html",
        question=q,
        quiz_id=quiz_id,
        q_index=q_index,
        total=len(questions),
        options=all_options,
        step=step,
        annotation=annotation,
        guess=guess,
        correct_answer=correct,
        active_nav="stimulus",
    )


@app.route("/stimulus/practice/results/<quiz_id>")
@login_required
def stimulus_practice_results(quiz_id):
    """Results for stimulus practice session."""
    quiz = db.load_quiz(quiz_id)
    if not quiz or not quiz.get("is_stimulus"):
        flash("Practice session not found.", "error")
        return redirect("/stimulus")

    answers = quiz["answers"]
    total = len(answers)
    correct = sum(1 for a in answers if a["is_correct"])
    pct = round(correct / total * 100, 1) if total > 0 else 0

    # Track stimulus literacy metrics
    guessed_correct = sum(1 for a in answers if a["guess"].strip() != "" and a["is_correct"])
    annotated = sum(1 for a in answers if a["annotation"].strip() != "")

    # Domain name lookup
    domains = kb.get_domains()
    domain_map = {d["id"]: d["name"] for d in domains}

    db.delete_quiz(quiz_id)

    return render_template("stimulus_results.html",
        answers=answers,
        total=total,
        correct=correct,
        pct=pct,
        guessed_correct=guessed_correct,
        annotated=annotated,
        domain_map=domain_map,
        active_nav="stimulus",
    )

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Socratic Tutor — optional "bring your own model" AI tutor.
#
# This is NOT a paid feature and NOT gated. It is plumbing: point the router
# and teacher at any OpenAI-compatible endpoint (a local llama-server or a
# cloud model) via the FCLE_TUTOR_ROUTER_URL / FCLE_TUTOR_TEACHER_URL env
# vars, or leave them unset and the tutor simply reports its models offline.
# ---------------------------------------------------------------------------

_tutor = tutor_engine.TutorEngine()

@app.route('/tutor')
@login_required
def tutor_page():
    """The AI Tutor now lives inside the unified Coach page."""
    return redirect('/coach')

@app.route('/tutor/chat', methods=['POST'])
@login_required
def tutor_chat():
    data = request.get_json(force=True)
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'error': 'Empty message'}), 400
    domain = data.get('domain')
    history = data.get('history', [])
    user_id = session["user_id"]
    
    # Save student message
    import sqlite3 as _sq
    try:
        _c = _sq.connect("data/user_progress.db")
        _c.execute("INSERT INTO tutor_messages (user_id, role, content, domain) VALUES (?, 'student', ?, ?)",
                   (user_id, message, domain))
        _c.commit()
        _c.close()
    except Exception:
        pass
    
    result = _tutor.chat(message, domain=domain, history=history)
    
    # Save tutor response
    try:
        _c = _sq.connect("data/user_progress.db")
        _c.execute("INSERT INTO tutor_messages (user_id, role, content, domain) VALUES (?, 'tutor', ?, ?)",
                   (user_id, result.get('response', ''), domain))
        _c.commit()
        _c.close()
    except Exception:
        pass
    
    return jsonify(result)

@app.route('/tutor/status')
def tutor_status():
    return jsonify(_tutor.check_servers())


@app.route('/tutor/history')
@login_required
def tutor_history():
    """Load persistent chat history for the current user."""
    user_id = session["user_id"]
    limit = request.args.get("limit", 50, type=int)
    import sqlite3 as _sq
    try:
        _c = _sq.connect("data/user_progress.db")
        _c.row_factory = _sq.Row
        rows = _c.execute(
            "SELECT role, content, domain, created_at FROM tutor_messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        _c.close()
        messages = [{"role": r["role"], "content": r["content"], "domain": r["domain"], "time": r["created_at"]} for r in reversed(rows)]
        return jsonify({"messages": messages})
    except Exception as e:
        return jsonify({"messages": [], "error": str(e)})

# Entry point
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    db.init_db()
    db.init_diagnostic_table()
    app.run(host="0.0.0.0", port=5003, debug=False)

