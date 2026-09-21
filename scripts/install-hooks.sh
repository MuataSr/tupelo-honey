#!/usr/bin/env sh
# Install the local git hooks for this repo. Run once per clone:
#
#     sh scripts/install-hooks.sh
#
# Hooks live in .git/hooks/ which is NOT tracked by git, so this script is what
# makes a fresh clone protected.
set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_DIR="$REPO_ROOT/.git/hooks"
mkdir -p "$HOOK_DIR"

cat > "$HOOK_DIR/pre-commit" <<'HOOK'
#!/usr/bin/env sh
# Block commits that introduce a credential. Installed by scripts/install-hooks.sh
if ! command -v python3 >/dev/null 2>&1; then
  echo "pre-commit: python3 not found; skipping secret scan" >&2
  exit 0
fi
if [ ! -f scripts/secret_scan.py ]; then
  exit 0
fi
if ! python3 scripts/secret_scan.py --staged; then
  echo "" >&2
  echo "Commit blocked: the staged changes look like they contain a credential." >&2
  echo "Read it from the environment instead (see .env.example)." >&2
  echo "If it was already committed, ROTATE it - removing the file is not enough." >&2
  exit 1
fi
exit 0
HOOK

chmod +x "$HOOK_DIR/pre-commit"
echo "installed: $HOOK_DIR/pre-commit"

cat > "$HOOK_DIR/pre-push" <<'HOOK'
#!/usr/bin/env sh
# Last line of defence: scan the whole history before anything leaves the machine.
if [ ! -f scripts/secret_scan.py ]; then exit 0; fi
if ! python3 scripts/secret_scan.py --all-history; then
  echo "" >&2
  echo "Push blocked: credentials found in history. ROTATE them, then purge:" >&2
  echo "  git filter-repo --replace-text <expressions> --force" >&2
  exit 1
fi
exit 0
HOOK

chmod +x "$HOOK_DIR/pre-push"
echo "installed: $HOOK_DIR/pre-push"
echo ""
echo "Done. Both hooks are active for this clone."
