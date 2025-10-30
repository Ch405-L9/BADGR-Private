#!/usr/bin/env bash
set -Eeuo pipefail

0) Safety: be in repo root

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "Not a git repo"; exit 1; }

1) Ensure git repo and clean remote

git init
if git remote | grep -q '^origin$'; then git remote remove origin; fi
git remote add origin https://github.com/Ch405-L9/badgr_bot-v13.git

2) Remove heavyweight paths from the index (keep on disk)

git rm -r --cached --ignore-unmatch .venv || true
git rm -r --cached --ignore-unmatch outputs || true
git rm -r --cached --ignore-unmatch node_modules || true
git add .gitignore

3) If this is the very first commit, amend it to drop big files

COMMITS=$(git rev-list --count HEAD || echo 0)
if [ "$COMMITS" -le 1 ]; then
git add -A
git commit --amend -m "Initial commit for badgr_bot-v13 (without venv, outputs, node_modules)"
else

Otherwise, new commit (history already has big blobs)

git add -A
git commit -m "Purge large artifacts from index and add .gitignore"
echo "Detected multiple commits. If push still fails due to history blobs, run the filter step below."
fi

4) Use main branch

git branch -M main

5) Push

git push -u origin main
echo "[done] Clean push attempted."

6) Optional: history rewrite if earlier commits contained large binaries

cat <<'NOTE'
If GitHub still rejects due to large blobs in older commits, run:

python3 - <<'PY'
import shutil, sys, subprocess
print("Checking git-filter-repo...")
rc = subprocess.call(["git", "filter-repo", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if rc != 0:
print("Installing git-filter-repo to ~/.local/bin ...")
subprocess.check_call(["bash","-lc","mkdir -p ~/.local/bin && curl -sSLo ~/.local/bin/git-filter-repo https://raw.githubusercontent.com/newren/git-filter-repo/main/git-filter-repo
 && chmod +x ~/.local/bin/git-filter-repo && echo 'export PATH=$HOME/.local/bin:$PATH' >> ~/.bashrc"])
print("Restart your shell or source ~/.bashrc and rerun the filter commands below.")
else:
print("git-filter-repo available.")
PY

Then rewrite history to drop common heavy paths:

git filter-repo --invert-paths --path .venv --path outputs --path node_modules

Finally force-push the cleaned history:

git push -u origin main --force

NOTE
