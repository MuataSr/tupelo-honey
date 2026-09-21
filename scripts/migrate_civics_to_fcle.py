#!/usr/bin/env python3
"""
Phase 0.2-0.4: Migrate civics KB to FCLE schema.
- Add fcle_domains table
- Add fcle_domain column to content
- Remap misconceptions from EOC benchmarks to FCLE domains
"""

import sqlite3
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
SRC = PROJECT_DIR.parent / "openstax-tutor" / "civics" / "data" / "civics.db"
DST = PROJECT_DIR / "data" / "tupelo.db"

# Step 1: Copy KB
print(f"Copying {SRC.name} → {DST.name}")
shutil.copy2(SRC, DST)

conn = sqlite3.connect(str(DST))
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Step 2: Create fcle_domains table
print("\nCreating fcle_domains table...")
c.execute("""
    CREATE TABLE IF NOT EXISTS fcle_domains (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        topics TEXT,          -- JSON array of topic strings
        fcle_question_count INTEGER DEFAULT 20
    )
""")

import json
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from data.fcle_domain_mapping import DOMAINS, DOMAIN_MAP

for d_id, d_meta in DOMAINS.items():
    c.execute("""
        INSERT INTO fcle_domains (id, name, description, topics, fcle_question_count)
        VALUES (?, ?, ?, ?, ?)
    """, (d_id, d_meta["name"], d_meta["description"],
          json.dumps(d_meta["topics"]), d_meta["fce_question_count"]))

print(f"  Inserted {len(DOMAINS)} domains")

# Step 3: Add fcle_domain column to content
print("\nAdding fcle_domain column to content...")
c.execute("ALTER TABLE content ADD COLUMN fcle_domain INTEGER")
for sid, domain in DOMAIN_MAP.items():
    c.execute("UPDATE content SET fcle_domain = ? WHERE id = ?", (domain, sid))
print(f"  Mapped {len(DOMAIN_MAP)} sections")

# Verify
c.execute("SELECT fcle_domain, COUNT(*) FROM content GROUP BY fcle_domain ORDER BY fcle_domain")
print("\n  Content distribution:")
for row in c.fetchall():
    print(f"    Domain {row[0]}: {row[1]} sections")

# Step 4: Remap misconceptions from EOC benchmarks to FCLE domains
# Each misconception has a benchmark_code (SS.7.CG.*). We need to map benchmarks → domains,
# then assign misconceptions to domains via their benchmark.

print("\nRemapping misconceptions to FCLE domains...")

# First, map benchmark codes to FCLE domains via their content sections
c.execute("""
    SELECT DISTINCT bs.benchmark_code, c.fcle_domain
    FROM benchmark_sections bs
    JOIN content c ON c.id = bs.section_id
    WHERE c.fcle_domain IS NOT NULL
""")
bm_domain = {}
for row in c.fetchall():
    bm, domain = row[0], row[1]
    if bm not in bm_domain:
        bm_domain[bm] = []
    if domain not in bm_domain[bm]:
        bm_domain[bm].append(domain)

# For benchmarks with multiple domains, pick the most common (mode)
from collections import Counter
bm_final = {}
for bm, domains in bm_domain.items():
    if len(domains) == 1:
        bm_final[bm] = domains[0]
    else:
        bm_final[bm] = Counter(domains).most_common(1)[0][0]

# Add fcle_domain column to misconceptions
c.execute("ALTER TABLE misconceptions ADD COLUMN fcle_domain INTEGER")

# Update each misconception based on its benchmark
updated = 0
unmapped = 0
c.execute("SELECT id, benchmark_code FROM misconceptions")
for row in c.fetchall():
    mid, bm = row[0], row[1]
    if bm in bm_final:
        c.execute("UPDATE misconceptions SET fcle_domain = ? WHERE id = ?", (bm_final[bm], mid))
        updated += 1
    else:
        unmapped += 1

print(f"  Mapped: {updated} misconceptions")
if unmapped:
    print(f"  Unmapped: {unmapped} misconceptions (no benchmark→section link)")

# Verify
c.execute("SELECT fcle_domain, COUNT(*) FROM misconceptions GROUP BY fcle_domain ORDER BY fcle_domain")
print("\n  Misconception distribution:")
for row in c.fetchall():
    d = row[0] if row[0] else "NULL"
    print(f"    Domain {d}: {row[1]}")

# Step 5: Remap key_terms to FCLE domains
print("\nRemapping key_terms to FCLE domains...")
c.execute("ALTER TABLE key_terms ADD COLUMN fcle_domain INTEGER")

# Key terms have a chapter column. Map chapters to domains via content.
c.execute("""
    SELECT DISTINCT c.chapter, c.fcle_domain
    FROM content c
    WHERE c.fcle_domain IS NOT NULL
""")
ch_domain = {}
for row in c.fetchall():
    ch, domain = row[0], row[1]
    if ch not in ch_domain:
        ch_domain[ch] = []
    if domain not in ch_domain[ch]:
        ch_domain[ch].append(domain)

ch_final = {}
for ch, domains in ch_domain.items():
    if len(domains) == 1:
        ch_final[ch] = domains[0]
    else:
        ch_final[ch] = Counter(domains).most_common(1)[0][0]

updated_terms = 0
c.execute("SELECT id, chapter FROM key_terms")
for row in c.fetchall():
    tid, ch = row[0], row[1]
    if ch in ch_final:
        c.execute("UPDATE key_terms SET fcle_domain = ? WHERE id = ?", (ch_final[ch], tid))
        updated_terms += 1

print(f"  Mapped: {updated_terms} key terms")

c.execute("SELECT fcle_domain, COUNT(*) FROM key_terms GROUP BY fcle_domain ORDER BY fcle_domain")
print("\n  Key term distribution:")
for row in c.fetchall():
    d = row[0] if row[0] else "NULL"
    print(f"    Domain {d}: {row[1]}")

# Step 6: Create FCLE-specific FTS index
print("\nCreating fcle_content_fts (domain-aware)...")
# Check if it already exists from a prior run
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='fcle_content_fts'")
if c.fetchone():
    c.execute("DROP TABLE IF EXISTS fcle_content_fts")

c.execute("""
    CREATE VIRTUAL TABLE fcle_content_fts
    USING fts5(section_title, fcle_domain, text)
""")

# Populate from content — match columns by position
c.execute("""
    INSERT INTO fcle_content_fts (section_title, fcle_domain, text)
    SELECT section_title, fcle_domain, text FROM content
""")
fts_count = c.execute("SELECT COUNT(*) FROM fcle_content_fts").fetchone()[0]
print(f"  Indexed {fts_count} sections")

# Commit
conn.commit()

# Final stats
print("\n=== FCLE DB Stats ===")
c.execute("SELECT COUNT(*) FROM fcle_domains")
print(f"  Domains: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM content")
print(f"  Content sections: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM misconceptions")
print(f"  Misconceptions: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM key_terms")
print(f"  Key terms: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM benchmarks")
print(f"  EOC benchmarks (kept for reference): {c.fetchone()[0]}")

conn.close()
print(f"\n✅ FCLE DB created at {DST}")
