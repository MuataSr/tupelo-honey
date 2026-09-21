# Tupelo Honey — Deployment Runbook

Deploy by git clone — no rsync of working trees.

## Target

- A small VPS dedicated to study apps
- nginx → gunicorn `127.0.0.1:5004` → Flask `wsgi:app`
- `<your-domain>` over HTTPS via Certbot

Choose a port that doesn't collide with other apps on the host.

## First deploy

```bash
# 1. Clone
git clone <repo-url> /opt/tupelo-study-app
cd /opt/tupelo-study-app

# 2. Venv + deps
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip install gunicorn

# 3. Env (never commit)
cat > .env << 'EOF'
FLASK_SECRET=<64-hex from: openssl rand -hex 24>
FLASK_ENV=production
EOF
chmod 600 .env

# 4. First boot (creates a fresh user_progress.db + schema)
venv/bin/python -c "import db; db.init_db()"

# 5. systemd unit
cat > /etc/systemd/system/tupelo-study-app.service << 'EOF'
[Unit]
Description=Tupelo Honey Nursing Prep (gunicorn)
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/tupelo-study-app
EnvironmentFile=/opt/tupelo-study-app/.env
ExecStart=/opt/tupelo-study-app/venv/bin/gunicorn -c gunicorn.conf.py -b 127.0.0.1:5004 wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload && systemctl enable --now tupelo-study-app

# 6. Nginx vhost proxying to 127.0.0.1:5004, then certbot
```

## Verify

```bash
curl -s -o /dev/null -w 'HTTP %{http_code}\n' https://<your-domain>/
curl -s -o /dev/null -w 'HTTP %{http_code}\n' https://<your-domain>/login
journalctl -u tupelo-study-app -n 50 --no-pager
```

## Code update

```bash
cd /opt/tupelo-study-app
cp data/tupelo.db "data/tupelo.db.bak-$(date +%Y%m%d-%H%M%S)"
git pull && venv/bin/pip install -r requirements.txt
systemctl restart tupelo-study-app
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://<your-domain>/
```

---

## Notes

- `data/user_progress.db` is gitignored and created fresh at first boot — never
  copy a dev DB to prod. `data/tupelo.db` (the content) **is** tracked; a deploy
  ships the current question bank with it.
- Quiz state is SQLite-backed (`active_quizzes`), so `workers = 2` is safe —
  nothing lives in worker RAM.
- `gunicorn.conf.py` recycles workers every ~400 requests (`max_requests`).
  Under sustained load that can cause a brief latency outlier; raise it before
  an exam-day traffic spike. See the performance table in `PROJECT_STATUS.md`.
- **Backup cron:** nightly `sqlite3 .backup` of `user_progress.db` plus an
  integrity check, keep 14 days.
- **Deploy key (read-only):** GitHub → Settings → Deploy keys → paste the
  host's `~/.ssh/id_ed25519.pub`.

---

## Pilot signup cap

The first release candidate is intentionally capped so a small droplet can never
be overrun. All knobs live in `.env` — no code change needed, edit and restart.

| Variable | Purpose |
|---|---|
| `PILOT_SIGNUP_CAP` | Max real students. `0` or unset = uncapped. |
| `PILOT_INTERNAL_EMAILS` | Comma-separated emails that never consume a seat. |
| `PILOT_BYPASS_KEY` | Secret; `?bypass=<key>` on `/signup` registers past the cap. |
| `PILOT_ADMIN_KEY` | Secret; `/admin/waitlist?key=<key>` lists the waitlist (`&format=csv` to export). |

Behaviour:

- Seats count **registered, non-anonymous users with an email**, minus
  `PILOT_INTERNAL_EMAILS`.
- The check runs **server-side and race-safe** (single `BEGIN IMMEDIATE` lock),
  so two simultaneous signups cannot both take the last seat.
- When full, `/signup` shows the pilot-full state with a waitlist form
  (`POST /waitlist`) instead of the registration form. No dead end.
- Waitlist entries land in the `waitlist` table; outreach is manual.
