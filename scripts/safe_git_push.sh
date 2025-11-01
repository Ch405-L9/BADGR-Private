#!/usr/bin/env bash
set -euo pipefail

ROOT="$(pwd)"
REMOTE_URL="https://github.com/Ch405-L9/BADGR-Private.git"
BRANCH_NAME="Agentik_v2_push"
WARN_SIZE_MB=100

echo "== SAFE GIT PUSH CHECKS =="
echo "Project root: $ROOT"
echo

# 1) ensure venv warning (optional)
if [ -d ".venv" ]; then
  echo "[INFO] .venv present. Make sure you activated it for local tasks."
fi

# 2) check for project .env with potential secrets and move it aside automatically (non-destructive)
if [ -f ".env" ]; then
  echo "[WARN] .env found in project root — moving to .env.local.backup to avoid committing secrets."
  mv .env .env.local.backup
  echo "[OK] .env moved -> .env.local.backup. A placeholder .env.example will be created."
  echo "GOOGLE_API_KEY=" > .env.example
  echo "GOOGLE_CSE_ID=" >> .env.example
fi

# 3) quick content secret scan (patterns)
echo
echo "-> scanning workspace for common secret patterns (quick)"
SECMATCH=$(grep -RIn --exclude-dir=.git --exclude-dir=.venv --exclude-dir=outputs -e "AIza[A-Za-z0-9_-]\{35\}" -e "AKIA[A-Z0-9]\{16\}" -e "BEGIN RSA PRIVATE KEY" -e "PRIVATE_KEY" -e "GOOGLE_API_KEY" -e "GOOGLE_CSE_ID" || true)
if [ -n "$SECMATCH" ]; then
  echo "[FAIL] Potential secret-like strings found:"
  echo "$SECMATCH"
  echo
  echo "You must remove/rotate these secrets before pushing. See docs: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository"
  exit 2
else
  echo "[OK] no obvious secret-like strings found (quick scan)"
fi

# 4) check repo init
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[OK] inside a git repo"
else
  echo "[INFO] not a git repo — initializing a new git repo"
  git init
  # create default .gitignore entries if missing
  if [ ! -f .gitignore ]; then
    cat > .gitignore <<'GITIGNORE'
# venv
.venv/
# env files
.env
.env.local
# outputs (optional)
outputs/
# python cache
__pycache__/
*.pyc
GITIGNORE
    git add .gitignore
    git commit -m "chore: add .gitignore (auto)"
  fi
fi

# 5) ensure origin remote usage
CURRENT_ORIGIN=$(git remote get-url origin 2>/dev/null || true)
if [ -z "$CURRENT_ORIGIN" ]; then
  echo "[INFO] no 'origin' remote set. Setting origin -> $REMOTE_URL"
  git remote add origin "$REMOTE_URL"
else
  echo "[INFO] current origin: $CURRENT_ORIGIN"
  if [ "$CURRENT_ORIGIN" != "$REMOTE_URL" ]; then
    echo "[WARN] origin differs from expected ($REMOTE_URL)."
    echo "If you want to change it run: git remote set-url origin $REMOTE_URL"
    echo "Aborting push to avoid accidental remote push."
    exit 3
  fi
fi

# 6) check for large files in working tree (simple)
echo
echo "-> checking for large files (> ${WARN_SIZE_MB}MB)"
LARGE_FILES=$(find . -path "./.git/*" -prune -o -type f -size +"${WARN_SIZE_MB}"M -print | sed 's|^\./||' || true)
if [ -n "$LARGE_FILES" ]; then
  echo "[WARN] Large files detected (>$WARN_SIZE_MB MB):"
  echo "$LARGE_FILES"
  echo "Consider using git-lfs or remove these files before pushing."
  exit 4
else
  echo "[OK] no large files detected"
fi

# 7) ensure at least one commit exists; if none, create initial commit safely
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "[OK] repository has commits"
else
  echo "[INFO] creating initial commit (all files staged) - you can amend later"
  git add -A
  git commit -m "chore(repo): initial commit — prepared by safe_git_push"
fi

# 8) confirm tests / SHN stamp presence (optional gate per LAWS)
if [ ! -f outputs/shn_small.json ] && [ ! -f outputs/shn_full.json ]; then
  echo "[WARN] No SHN handoff found (outputs/shn_small.json or outputs/shn_full.json)."
  echo "Creating a minimal outputs/shn_small.json for traceability."
  mkdir -p outputs
  cat > outputs/shn_small.json <<JSON
{"shn_version":"1.1.0","doc_type":"SHN-SM","collected_at_utc":"$(date -u +'%Y-%m-%dT%H:%M:%SZ')","notes":"auto-created minimal SHN-SM before push"}
JSON
  git add outputs/shn_small.json
  git commit -m "chore(shn): add minimal outputs/shn_small.json for traceability" || true
fi

# 9) create a branch and push
echo
echo "-> creating/checkout branch: $BRANCH_NAME"
git checkout -B "$BRANCH_NAME"

echo "-> pushing to origin/$BRANCH_NAME (upstream will be set)"
git push -u origin "$BRANCH_NAME"

echo
echo "SUCCESS: branch pushed to origin/$BRANCH_NAME"
echo "Create a PR on GitHub against your main branch and ensure required status checks / LAWS workflow pass before merge."
