"""
Tupelo Tutor Engine — optional "bring your own model" Socratic tutor.

This is NOT a paid feature and NOT gated. It is plumbing: an OpenAI-compatible
chat endpoint powers a router (intent classification) and a teacher (Socratic
response grounded in the app's own knowledge base). Point them at a local
llama-server or any cloud model via the TUPELO_TUTOR_ROUTER_URL and
TUPELO_TUTOR_TEACHER_URL env vars. Defaults assume a local llama-server on ports
8082 (router) and 8083 (teacher); leave them unset and the tutor reports its
models offline.
"""

import json
import os
import re
import sqlite3
import requests
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "tupelo.db"


def _env(*names, default):
    """First env var that is set, so legacy framework names keep working."""
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


ROUTER_URL = _env("TUPELO_TUTOR_ROUTER_URL", "FCLE_TUTOR_ROUTER_URL",
                  default="http://localhost:8082/v1/chat/completions")
TEACHER_URL = _env("TUPELO_TUTOR_TEACHER_URL", "FCLE_TUTOR_TEACHER_URL",
                   default="http://localhost:8083/v1/chat/completions")

DOMAIN_MAP = {
    1: "Reading",
    2: "Mathematics",
    3: "Science",
    4: "English and Language Usage",
}

ROUTER_PROMPT = (
    'Classify the student message. Reply with ONLY a JSON object. '
    'Domains: 1=Reading, 2=Mathematics, 3=Science, 4=English and Language Usage. '
    'Format: {"intent":"concept_question","domain":3,"topics":["mitosis"],"difficulty":"basic"}'
)

TEACHER_PROMPT = (
    "You are a Socratic tutor for the ATI TEAS and HESI A2 nursing admission "
    "exams.\n\n"
    "Rules:\n"
    "1. GUIDE — ask probing questions that lead students to discover answers. Never just give the answer.\n"
    "2. GROUND — use the provided knowledge base context to keep responses accurate.\n"
    "3. CORRECT — if the student shows a misconception from KNOWN MISCONCEPTIONS, gently redirect.\n"
    "4. CONCISE — 2-4 sentences plus one follow-up question. No lectures.\n"
    "5. SPECIFIC — reference the relevant concept, term, formula, or body system by name when it helps.\n"
    "6. ADAPT — match difficulty to the student's level.\n\n"
    "DOMAIN: {domain_name}\n\n{kb_context}"
)


class TutorEngine:
    def __init__(self, db_path=None, router_url=None, teacher_url=None):
        self.db_path = str(db_path or DB_PATH)
        self.router_url = router_url or ROUTER_URL
        self.teacher_url = teacher_url or TEACHER_URL

    def _db(self):
        return sqlite3.connect(self.db_path)

    # ── KB Retrieval ──────────────────────────────────────────────

    def retrieve_context(self, query, domain=None, limit=5):
        results = {"content": [], "terms": [], "misconceptions": []}
        db = self._db()
        cur = db.cursor()

        # Content sections via FTS
        try:
            fts_q = query.replace('"', '""')
            dom = f"AND c.fcle_domain = {int(domain)}" if domain else ""
            rows = cur.execute(f"""
                SELECT c.section_title, c.text, c.fcle_domain, c.chapter_title
                FROM content_fts f
                JOIN content c ON c.id = f.rowid
                WHERE content_fts MATCH ?
                {dom}
                ORDER BY rank LIMIT ?
            """, (fts_q, limit)).fetchall()
            results["content"] = [
                {"section": r[0], "text": r[1][:500], "domain": r[2], "chapter": r[3]}
                for r in rows
            ]
        except Exception:
            pass

        # Key terms via FTS
        try:
            words = query.split()
            term_q = " OR ".join(f'"{w}"' for w in words[:5])
            rows = cur.execute("""
                SELECT kt.term, kt.definition, kt.fcle_domain
                FROM terms_fts f
                JOIN key_terms kt ON kt.id = f.rowid
                WHERE terms_fts MATCH ?
                LIMIT ?
            """, (term_q, limit)).fetchall()
            results["terms"] = [
                {"term": r[0], "definition": r[1], "domain": r[2]}
                for r in rows
            ]
        except Exception:
            pass

        # Misconceptions (domain-filtered or random sample)
        try:
            if domain:
                rows = cur.execute("""
                    SELECT misconception, correction, difficulty
                    FROM misconceptions WHERE fcle_domain = ?
                    ORDER BY RANDOM() LIMIT ?
                """, (int(domain), 5)).fetchall()
            else:
                rows = cur.execute("""
                    SELECT misconception, correction, difficulty
                    FROM misconceptions ORDER BY RANDOM() LIMIT 3
                """).fetchall()
            results["misconceptions"] = [
                {"misconception": r[0], "correction": r[1], "difficulty": r[2]}
                for r in rows
            ]
        except Exception:
            pass

        db.close()
        return results

    # ── Router ────────────────────────────────────────────────────

    def classify_intent(self, message, history=None):
        prompt = ROUTER_PROMPT + "\n\nStudent: " + message
        messages = [{"role": "user", "content": prompt}]

        try:
            resp = requests.post(self.router_url, json={
                "messages": messages,
                "max_tokens": 200,
                "temperature": 0.0,
            }, timeout=20)
            text = resp.json()["choices"][0]["message"]["content"].strip()
            # Strip code fences if present
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
            return json.loads(text.strip())
        except Exception as e:
            return {
                "intent": "concept_question",
                "domain": None,
                "topics": [message],
                "difficulty": "basic",
                "_fallback": True,
                "_error": str(e),
            }

    # ── Teacher ───────────────────────────────────────────────────

    def generate_response(self, message, kb_context, domain=None, history=None):
        domain_name = DOMAIN_MAP.get(domain, "General")

        ctx_parts = []
        if kb_context["content"]:
            ctx_parts.append("RELEVANT CONTENT:")
            for c in kb_context["content"][:3]:
                ctx_parts.append("- " + c["section"] + ": " + c["text"])
        if kb_context["terms"]:
            ctx_parts.append("\nKEY TERMS:")
            for t in kb_context["terms"][:5]:
                ctx_parts.append("- " + t["term"] + ": " + t["definition"])
        if kb_context["misconceptions"]:
            ctx_parts.append("\nKNOWN MISCONCEPTIONS (redirect if student shows these):")
            for m in kb_context["misconceptions"][:3]:
                ctx_parts.append("- Misconception: " + m["misconception"] + " -> Correction: " + m["correction"])

        kb_str = "\n".join(ctx_parts) if ctx_parts else "No specific KB context found."
        system = TEACHER_PROMPT.format(domain_name=domain_name, kb_context=kb_str)

        messages = [{"role": "system", "content": system}]
        if history:
            for h in history[-6:]:
                role = "user" if h.get("role") == "student" else "assistant"
                messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": message})

        try:
            resp = requests.post(self.teacher_url, json={
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.7,
            }, timeout=60)
            content = resp.json()["choices"][0]["message"]["content"].strip()
            return content or "I'm not sure how to respond to that. Could you rephrase?"
        except Exception as e:
            return "I'm having trouble connecting right now. Please try again. (Error: " + str(e) + ")"

    # ── Full Pipeline ─────────────────────────────────────────────

    def chat(self, message, domain=None, history=None):
        intent = self.classify_intent(message, history)
        effective_domain = domain or intent.get("domain")
        query = " ".join(intent.get("topics", [])) or message
        kb = self.retrieve_context(query, domain=effective_domain)
        response = self.generate_response(
            message, kb, domain=effective_domain, history=history
        )
        return {
            "response": response,
            "intent": intent,
            "domain": effective_domain,
            "domain_name": DOMAIN_MAP.get(effective_domain),
            "kb_hits": {
                "content": len(kb["content"]),
                "terms": len(kb["terms"]),
                "misconceptions": len(kb["misconceptions"]),
            },
        }

    # ── Health Check ──────────────────────────────────────────────

    def check_servers(self):
        status = {"router": False, "teacher": False}
        try:
            r = requests.get(
                self.router_url.replace("/v1/chat/completions", "/health"), timeout=3
            )
            status["router"] = r.status_code == 200
        except Exception:
            pass
        try:
            r = requests.get(
                self.teacher_url.replace("/v1/chat/completions", "/health"), timeout=3
            )
            status["teacher"] = r.status_code == 200
        except Exception:
            pass
        return status
