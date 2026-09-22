# Tupelo Honey — Project Status

**Last Updated:** 2026-09-21 by Ann-E
**Current Phase:** **Content complete, pre-deploy** — running locally; production host not yet chosen
**Sibling project:** [Sabal](https://github.com/MuataSr/sabal) (FCLE) — same exam-prep
framework, different content, separate deployment.

---

## What Is This

A web-based study app for the **ATI TEAS** and **HESI A2** nursing admission
exams. Students practice multiple-choice questions across four domains with
feedback modes, and the app tracks progress, mastery, and spaced review.

---

## Database Status

**Question DB:** `data/tupelo.db` — **2,506 questions**, zero nulls, zero
duplicates, zero letter references in explanations.

| Domain | Count |
|--------|-------|
| Reading | 581 |
| Math | 580 |
| Science | 686 |
| English & Language Usage | 659 |
| **Total** | **2,506** |

- Every question has a content-based explanation (no "Option B is wrong" —
  explanations survive answer shuffling).
- LaTeX math is preserved and rendered client-side (KaTeX).
- `wrong_answers` stored as JSON; `explanation` is the correct-answer rationale.

**User Progress DB:** `data/user_progress.db`

- Tables: `users`, `quiz_sessions`, `answers`, `topic_mastery`, `review_queue`,
  `diagnostic_baselines`, `tutor_messages`, `active_quizzes`
- **Auth model: registered users only — no anonymous accounts, no passwords.**
  Registration is email + display name; each account gets a 32-char
  `access_token` that is its personal dashboard link (`/?token=...`).
- Auth resolution order: session → `?token=` query param → `access_token`
  cookie. Stale or anonymous session ids are dropped, never honored.
- WAL journal mode (concurrent readers, one writer).

---

## App Stack

| Component | Details |
|-----------|---------|
| Backend | Flask, `app.py` (~1,700 lines) |
| Templates | Jinja2 HTML in `templates/` |
| CSS | `static/css/` — cream/white palette, navy text |
| Content | SQLite `data/tupelo.db` |
| WSGI | gunicorn, `gunicorn.conf.py` (2 workers × 4 threads, gthread) |
| Dependencies | Flask, python3 stdlib, requests — no heavy frameworks |

---

## Content Remediation (September 2026)

A four-bank integrity pass, because a bank is only as good as its answer key.

| Pass | Items | Detail |
|------|-------|--------|
| Question rescue | 93 | Source parser dropped single-line and parenthesized option formats; all recovered (2,415 → 2,508) |
| Letter-reference rewrite | 1,507 | Explanations argued by option letter ("Option B states…"), which breaks under shuffling. Rewritten to argue from content |
| Answer-key audit | 77 | Every keyed item re-derived by hand. 25 keys corrected, 13 option sets repaired, 27 stems reworked, 10 Math/Science fixes, 2 duplicates dropped |
| Factual audit (Tier 1) | 217 | Explanations that misstated an option, carried an arithmetic slip, or described options no longer in the item |
| Factual audit (Tier 2) | 26 | Rules overstated as absolutes, imprecise definitions — reviewed and corrected |
| Duplicates | 2 | Dropped (`Q520` dup of `Q390`; `Q1790` dup of `Q1547`) |

**Root cause worth remembering:** the upstream bank stored the answer key as a
bare option *letter* while the options themselves were scrambled, so a stored
key could point at the wrong option while looking correct. **Always verify a key
by value, never by position.**

**Verification after every pass:** backups taken before each write; after the
final pass — 2,506 questions, 0 letter references, 0 malformed JSON, 0
missing/short explanations.

---

## Performance (measured, September 2026)

Load-tested against the real app under gunicorn with the production config
(2 workers × 4 threads) pinned to **one CPU**, driving the real quiz flow
(login → start quiz → question → answer) with realistic think time.

| Concurrent students | Throughput | p50 | p95 | Errors |
|---|---|---|---|---|
| 100 | 26 req/s | 3 ms | 15 ms | 0 |
| 300 | 239 req/s | 4 ms | 28 ms | 0 |
| 600 | 394 req/s | 272 ms | 424 ms | 2 |

- **Ceiling is CPU:** ~3 ms CPU per request, so one core sustains roughly
  **330–400 req/s** before latency degrades.
- **Registration is not the constraint** — accounts are SQLite rows; 100,000+ is
  unremarkable.
- **Note:** `max_requests = 400` recycles workers under sustained hammering and
  can produce a brief latency outlier. Worth tuning before an exam-day spike.

---

## Remaining Roadmap

- [x] **Production deploy: LIVE at https://tupelo.mu2.solutions** (2026-09-22).
  systemd service on the Sabal droplet at `/opt/tupelo-study-app`, gunicorn on
  127.0.0.1:5003 behind nginx, Let's Encrypt TLS with auto-renewal. Hard
  resource guards (`MemoryMax=350M`, `CPUWeight=50`, `TasksMax=64`) keep the
  sibling app unaffected; verified after every deploy step.
- [ ] **PWA support** — service worker + manifest for install-to-homescreen
- [ ] **Mobile polish** — verify responsive layout on small screens

---

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | Main Flask application (routes, quiz logic, auth) |
| `kb.py` | Question loading from SQLite |
| `db.py` | User progress DB operations |
| `tutor_engine.py` | Optional Socratic tutor (bring-your-own endpoint) |
| `gunicorn.conf.py` / `wsgi.py` | Production WSGI entry point |
| `templates/base.html` | Base layout (navbar, footer, nav drawer) |
| `templates/quiz.html` | Quiz UI + per-choice feedback breakdown |
| `data/tupelo.db` | Question bank (2,506 questions) |
| `data/user_progress.db` | User accounts + progress (not committed) |
