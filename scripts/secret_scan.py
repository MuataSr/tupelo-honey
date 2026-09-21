#!/usr/bin/env python3
"""
Credential scanner — blocks secrets from ever entering this repo again.

Modes:
  secret_scan.py                scan all git-tracked files
  secret_scan.py --staged       scan content staged in the index (pre-commit hook)
  secret_scan.py --all-history  scan every blob in every commit (slow; pre-release gate)

Exit 0 = clean, 1 = findings (so it works as a blocking hook).

Stdlib only. No install, no network.
"""
import os, re, subprocess, sys

# --- patterns -------------------------------------------------------------
# Ordered roughly most-specific first. Each is (name, regex).
PATTERNS = [
    ("Private key block",      re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----")),
    ("AWS access key id",      re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16,20}\b")),
    ("GitHub token",           re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("Anthropic key",          re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("OpenAI key",             re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{24,}\b")),
    ("Google API key",         re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("Slack token",            re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("Z.AI / BigModel key",    re.compile(r"\b[0-9a-f]{32}\.[A-Za-z0-9_\-]{12,}\b")),
    ("Stripe key",             re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("SendGrid key",           re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}\b")),
    ("Generic secret assign",  re.compile(
        r"""(?ix)\b(?:api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key|
                        private[_-]?key|client[_-]?secret|auth[_-]?token)\b
                     \s*[:=]\s*
                     ["'](?P<val>[^"'\s]{12,})["']""")),
]

# --- allowlist: things that look like secrets but are not ------------------
PLACEHOLDER = re.compile(
    r"""(?ix)^(?:
        |your[-_].*|.*[-_]here|changeme|placeholder|example|dummy|sample|redacted
        |x{6,}|\*{6,}|REMOVED[-_]ROTATED[-_]KEY
        |os\.environ.*|getenv.*|\$\{.*\}.*|<.*>.*|%.*%|process\.env.*
        |null|none|true|false|test|todo
    )$""")

BINARY_EXT = {".png",".jpg",".jpeg",".gif",".webp",".ico",".woff",".woff2",
              ".ttf",".otf",".pdf",".zip",".gz",".tgz",".mp3",".mp4",".ogg",".wav",".db"}
SKIP_DIRS = {".git",".venv","venv","node_modules","__pycache__","dist","build",".mypy_cache"}
MAX_SCAN_BYTES = 64 * 1024 * 1024


def decode(raw, path=""):
    """Turn a blob into text for scanning. Never raises.

    Two earlier behaviours were both wrong. Binaries not listed in BINARY_EXT crashed the
    strict utf-8 decode, and the pre-commit hook then reported the crash as "looks like a
    credential" - which is how a commit of data/fcle.db got blocked. And binaries that WERE
    listed were skipped outright, which is a silent blind spot in a repo that commits a
    SQLite content database: a key sitting in a content row would never be seen.

    So: decode everything, and use latin-1 for binary because it maps every byte to a
    character, so ASCII credentials inside a binary stay findable.
    """
    if not isinstance(raw, (bytes, bytearray)):
        return raw
    raw = bytes(raw)
    if len(raw) > MAX_SCAN_BYTES:
        print(f"  [skip] {path or 'blob'} is {len(raw) // (1024*1024)} MB, over the "
              f"{MAX_SCAN_BYTES // (1024*1024)} MB scan cap - raise MAX_SCAN_BYTES to scan it",
              file=sys.stderr)
        return ""
    is_binary = b"\x00" in raw[:8192] or os.path.splitext(path)[1].lower() in BINARY_EXT
    return raw.decode("latin-1" if is_binary else "utf-8", errors="replace")


def allowed(value: str) -> bool:
    """True = ignore this candidate.

    Deliberately conservative. An earlier version also required the value to
    contain BOTH a letter and a digit "to be a plausible key" -- that silently
    skipped real-format keys with no digits (several vendor tokens, and PEM
    headers). A scanner with a silent blind spot is worse than no scanner,
    because it creates false confidence. Only explicit placeholders are ignored.
    """
    v = value.strip().strip("\"'")
    if len(v) < 8:
        return True
    if PLACEHOLDER.match(v):
        return True
    return False


WINDOW = 4000
OVERLAP = 512


def scan_text(name, text, findings):
    """Scan every line, including very long ones.

    Long lines used to be skipped entirely to keep the regexes cheap. That is exactly
    where a blind spot lives: a minified bundle, or one line of a binary blob, can be
    thousands of characters and would never be looked at. Scan them in overlapping
    windows instead, so a token spanning a boundary is still matched.
    """
    for i, line in enumerate(text.splitlines(), 1):
        if len(line) <= WINDOW:
            windows = (line,)
        else:
            windows = tuple(line[j:j + WINDOW + OVERLAP]
                            for j in range(0, len(line), WINDOW))
        for window in windows:
            for label, rx in PATTERNS:
                for m in rx.finditer(window):
                    val = m.groupdict().get("val") or m.group(0)
                    if allowed(val):
                        continue
                    findings.append((name, i, label, val))


def tracked_files():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout
    return [f for f in out.splitlines() if f.strip()]


def staged_files():
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                         capture_output=True, text=True).stdout
    return [f for f in out.splitlines() if f.strip()]


def show(path, staged):
    try:
        if staged:
            # No text=True: let git hand back bytes and decode them here, so a binary
            # in the index cannot raise inside subprocess and be read as a finding.
            r = subprocess.run(["git", "show", f":{path}"], capture_output=True)
            return decode(r.stdout, path)
        with open(path, "rb") as fh:
            return decode(fh.read(), path)
    except OSError:
        return ""


def history_blobs():
    """Every blob in every commit (pre-release gate)."""
    revs = subprocess.run(["git", "rev-list", "--all"], capture_output=True, text=True).stdout.split()
    seen = set()
    for rev in revs:
        for line in subprocess.run(["git", "ls-tree", "-r", rev], capture_output=True,
                                   text=True).stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            sha, path = parts[2], parts[3]
            if sha in seen:
                continue
            seen.add(sha)
            body = decode(subprocess.run(["git", "cat-file", "-p", sha],
                                         capture_output=True).stdout, path)
            yield f"{rev[:10]}:{path}", decode(body, path)


def main():
    args = set(sys.argv[1:])
    findings = []

    if "--all-history" in args:
        count = 0
        for name, body in history_blobs():
            count += 1
            scan_text(name, body, findings)
        print(f"scanned {count} blobs across all commits")
    elif "--staged" in args:
        files = staged_files()
        for f in files:
            scan_text(f, show(f, True), findings)
        print(f"scanned {len(files)} staged file(s)")
    else:
        files = tracked_files()
        for f in files:
            if any(part in SKIP_DIRS for part in f.split(os.sep)):
                continue
            scan_text(f, show(f, False), findings)
        print(f"scanned {len(files)} tracked file(s)")

    if findings:
        print(f"\n{len(findings)} POTENTIAL CREDENTIAL(S) FOUND\n")
        for name, line, label, val in findings[:60]:
            masked = val[:6] + "..." + val[-4:] if len(val) > 12 else "***"
            print(f"  {label:22s} {name}:{line}  {masked}")
        if len(findings) > 60:
            print(f"  ... and {len(findings)-60} more")
        print("\nRemediation: remove the literal, read it from the environment "
              "(see .env.example). If it was ever committed, ROTATE the credential — "
              "deleting the file does not remove it from history.")
        return 1
    print("no credentials detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
