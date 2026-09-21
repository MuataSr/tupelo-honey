# gunicorn config — Tupelo Nursing Exam Prep
# Multi-worker safe: quiz state lives in SQLite (active_quizzes table), not RAM.
bind = "127.0.0.1:5002"
workers = 2
threads = 4
timeout = 120
# Recycle workers periodically: caps any slow memory growth / rare leak so a
# long-running pilot can't degrade. Safe because session state is a signed
# cookie and quiz state lives in SQLite (active_quizzes) — nothing lives in RAM.
max_requests = 400
max_requests_jitter = 50
accesslog = "-"
errorlog = "-"
loglevel = "info"
