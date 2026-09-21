#!/usr/bin/env python3
"""Create the questions table for FCLE study app."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "tupelo.db"

conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

c.execute("""CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fcle_domain INTEGER NOT NULL CHECK(fcle_domain BETWEEN 1 AND 4),
    topic TEXT NOT NULL,
    difficulty TEXT NOT NULL CHECK(difficulty IN ('easy','medium','hard')),
    question TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    wrong_answers TEXT NOT NULL,
    explanation TEXT NOT NULL,
    stimulus TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)""")

# FTS for searching questions
c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS questions_fts USING fts5(
    question, correct_answer, explanation, topic,
    content=questions, content_rowid=id
)""")

conn.commit()
print("✅ questions + questions_fts tables created")
conn.close()
