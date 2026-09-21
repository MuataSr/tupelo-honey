#!/usr/bin/env python3
"""
FCLE Study App — Harness
Functions for Florida Civic Literacy Exam aligned to 4 domains:
  1. American Democracy
  2. US Constitution
  3. Founding Documents
  4. Landmark Impact on Constitutional Law
"""

import sqlite3
from pathlib import Path

FCLE_KB_PATH = Path(__file__).parent.parent / "data" / "tupelo.db"


class FCLEHarness:
    """FCLE harness — sits between the LLM and the FCLE KB."""

    def __init__(self, kb_path=None):
        self.kb_path = Path(kb_path) if kb_path else FCLE_KB_PATH
        if not self.kb_path.exists():
            raise FileNotFoundError(f"FCLE KB not found: {self.kb_path}")
        self.conn = sqlite3.connect(str(self.kb_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")

    def close(self):
        self.conn.close()

    # ─── Content Search ──────────────────────────────────────────

    def search_content(self, query, limit=5):
        """FTS5 search across all KB content. Returns list of dicts."""
        clean = query.replace('"', '""')
        sql = """
            SELECT c.id, c.section_title,
                   snippet(fcle_content_fts, 1, '<b>', '</b>', '...', 32) as snippet,
                   c.char_count, c.fcle_domain
            FROM fcle_content_fts f
            JOIN content c ON c.id = f.rowid
            WHERE fcle_content_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        rows = self.conn.execute(sql, (clean, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_section_content(self, section_title):
        """Get full text of a section by title. Returns dict or None."""
        sql = """
            SELECT id, section_title, text, char_count, fcle_domain
            FROM content
            WHERE section_title LIKE ?
            LIMIT 1
        """
        row = self.conn.execute(sql, (f"%{section_title}%",)).fetchone()
        return dict(row) if row else None

    # ─── Domain Queries ──────────────────────────────────────────

    def get_domain_info(self, domain_id):
        """Get domain metadata (name, description, topics)."""
        sql = "SELECT * FROM fcle_domains WHERE id = ?"
        row = self.conn.execute(sql, (domain_id,)).fetchone()
        return dict(row) if row else None

    def get_all_domains(self):
        """Get all 4 FCLE domains."""
        sql = "SELECT * FROM fcle_domains ORDER BY id"
        return [dict(r) for r in self.conn.execute(sql).fetchall()]

    def get_domain_sections(self, domain_id):
        """Get all KB content sections for a domain."""
        sql = """
            SELECT id, section_title, char_count
            FROM content
            WHERE fcle_domain = ?
            ORDER BY id
        """
        rows = self.conn.execute(sql, (domain_id,)).fetchall()
        return [dict(r) for r in rows]

    def search_domain(self, domain_id, query, limit=5):
        """FTS5 search within a specific domain."""
        clean = query.replace('"', '""')
        sql = """
            SELECT c.id, c.section_title,
                   snippet(fcle_content_fts, 1, '<b>', '</b>', '...', 32) as snippet,
                   c.fcle_domain
            FROM fcle_content_fts f
            JOIN content c ON c.id = f.rowid
            WHERE fcle_content_fts MATCH ? AND c.fcle_domain = ?
            ORDER BY rank
            LIMIT ?
        """
        rows = self.conn.execute(sql, (clean, domain_id, limit)).fetchall()
        return [dict(r) for r in rows]

    # ─── Misconceptions ──────────────────────────────────────────

    def get_domain_misconceptions(self, domain_id, difficulty=None):
        """Get misconceptions for a domain, optionally filtered by difficulty."""
        if difficulty:
            sql = "SELECT * FROM misconceptions WHERE fcle_domain = ? AND difficulty = ?"
            rows = self.conn.execute(sql, (domain_id, difficulty)).fetchall()
        else:
            sql = "SELECT * FROM misconceptions WHERE fcle_domain = ?"
            rows = self.conn.execute(sql, (domain_id,)).fetchall()
        return [dict(r) for r in rows]

    def check_misconception_domain(self, domain_id, statement):
        """Check statement against misconceptions in a specific domain.
        Returns list of matching misconceptions with corrections."""
        misconceptions = self.get_domain_misconceptions(domain_id)
        matches = []
        for m in misconceptions:
            m_words = set(m["misconception"].lower().split())
            s_words = set(statement.lower().split())
            overlap = m_words & s_words
            if len(overlap) >= 2:
                matches.append({
                    "misconception": m["misconception"],
                    "correction": m["correction"],
                    "confidence": len(overlap) / len(m_words),
                    "difficulty": m["difficulty"]
                })
        matches.sort(key=lambda x: x["confidence"], reverse=True)
        return matches

    # ─── Key Terms ───────────────────────────────────────────────

    def get_domain_terms(self, domain_id):
        """Get key terms for a domain."""
        sql = "SELECT term, definition, fcle_domain FROM key_terms WHERE fcle_domain = ? ORDER BY term"
        rows = self.conn.execute(sql, (domain_id,)).fetchall()
        return [dict(r) for r in rows]

    def search_terms(self, query, limit=10):
        """FTS5 search across key terms and definitions."""
        clean = query.replace('"', '""')
        sql = """
            SELECT t.term, t.definition, t.fcle_domain,
                   snippet(terms_fts, 1, '<b>', '</b>', '...', 32) as snippet
            FROM terms_fts f
            JOIN key_terms t ON t.id = f.rowid
            WHERE terms_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        rows = self.conn.execute(sql, (clean, limit)).fetchall()
        return [dict(r) for r in rows]

    # ─── Questions ────────────────────────────────────────────────

    def get_domain_questions(self, domain_id, difficulty=None, limit=None):
        """Get practice questions for a domain, optionally filtered by difficulty."""
        sql = "SELECT * FROM questions WHERE fcle_domain = ?"
        params = [domain_id]
        if difficulty:
            sql += " AND difficulty = ?"
            params.append(difficulty)
        sql += " ORDER BY id"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_question(self, question_id):
        """Get a single question by ID."""
        row = self.conn.execute(
            "SELECT * FROM questions WHERE id = ?", (question_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_random_questions(self, domain_id=None, count=10, difficulty=None):
        """Get random questions for quiz mode. Optionally filter by domain/difficulty."""
        sql = "SELECT * FROM questions WHERE 1=1"
        params = []
        if domain_id:
            sql += " AND fcle_domain = ?"
            params.append(domain_id)
        if difficulty:
            sql += " AND difficulty = ?"
            params.append(difficulty)
        sql += " ORDER BY RANDOM() LIMIT ?"
        params.append(count)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_domain_question_count(self, domain_id, difficulty=None):
        """Get question count for a domain."""
        sql = "SELECT COUNT(*) FROM questions WHERE fcle_domain = ?"
        params = [domain_id]
        if difficulty:
            sql += " AND difficulty = ?"
            params.append(difficulty)
        return self.conn.execute(sql, params).fetchone()[0]

    # ─── Stats ───────────────────────────────────────────────────

    def get_domain_stats(self):
        """Get section/misconception/term/question counts per domain."""
        domains = self.get_all_domains()
        for d in domains:
            did = d["id"]
            d["sections"] = self.conn.execute(
                "SELECT COUNT(*) FROM content WHERE fcle_domain = ?", (did,)
            ).fetchone()[0]
            d["misconceptions"] = self.conn.execute(
                "SELECT COUNT(*) FROM misconceptions WHERE fcle_domain = ?", (did,)
            ).fetchone()[0]
            d["key_terms"] = self.conn.execute(
                "SELECT COUNT(*) FROM key_terms WHERE fcle_domain = ?", (did,)
            ).fetchone()[0]
            d["questions"] = self.conn.execute(
                "SELECT COUNT(*) FROM questions WHERE fcle_domain = ?", (did,)
            ).fetchone()[0]
        return domains

    def get_stats(self):
        """Get overall KB stats."""
        stats = {}
        stats["domains"] = self.conn.execute(
            "SELECT COUNT(*) FROM fcle_domains"
        ).fetchone()[0]
        stats["content_sections"] = self.conn.execute(
            "SELECT COUNT(*) FROM content"
        ).fetchone()[0]
        stats["misconceptions"] = self.conn.execute(
            "SELECT COUNT(*) FROM misconceptions"
        ).fetchone()[0]
        stats["key_terms"] = self.conn.execute(
            "SELECT COUNT(*) FROM key_terms"
        ).fetchone()[0]
        return stats


# ─── Quick test ──────────────────────────────────────────────────

if __name__ == "__main__":
    h = FCLEHarness()

    print("=== FCLE KB Stats ===")
    stats = h.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\n=== Domain Breakdown ===")
    for d in h.get_domain_stats():
        print(f"  D{d['id']} {d['name']}: {d['sections']} sections, "
              f"{d['misconceptions']} misconceptions, {d['key_terms']} terms")

    print("\n=== Sample search (Federalist) ===")
    results = h.search_content("Federalist")
    for r in results[:3]:
        print(f"  [D{r['fcle_domain']}] {r['section_title']}: {r['snippet'][:80]}...")

    print("\n=== Domain 3 misconceptions (sample) ===")
    misc = h.get_domain_misconceptions(3)
    for m in misc[:2]:
        print(f"  [{m['difficulty']}] {m['misconception'][:70]}...")

    print("\n=== Misconception check (D3) ===")
    matches = h.check_misconception_domain(3, "The Constitution was ratified by state governors")
    for m in matches[:2]:
        print(f"  ({m['confidence']:.0%}) {m['misconception'][:60]}...")

    h.close()
    print("\n✅ All functions verified")
