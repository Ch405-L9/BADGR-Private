#!/bin/bash

FAIL_COUNT=0

echo "=== PRE-PUSH CHECKS ==="
echo ""

# Install gitleaks
if ! command -v gitleaks &> /dev/null; then
    echo "Installing gitleaks..."
    curl -sSfL https://github.com/gitleaks/gitleaks/releases/download/v8.18.1/gitleaks_8.18.1_linux_x64.tar.gz | tar -xz
    sudo mv gitleaks /usr/local/bin/ 2>/dev/null || mv gitleaks ~/.local/bin/
fi

# Create .gitleaksignore (excludes test files and .env)
cat > .gitleaksignore << 'EOF'
.env
*.env
*test*.py
*test*.txt
Give_to_engineer*
ENV-corrected.txt
Terminal-Problems.txt
PROBLEMS.txt
EOF

# Git checks
if git rev-parse --git-dir > /dev/null 2>&1; then
    echo "[PASS] Git repository"
    git remote get-url origin &>/dev/null && echo "[PASS] Remote configured" || { echo "[FAIL] No remote"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    [ "$BRANCH" != "HEAD" ] && echo "[PASS] On branch: $BRANCH" || { echo "[FAIL] Detached HEAD"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
    git ls-files -u | grep -q . && { echo "[FAIL] Merge conflicts"; FAIL_COUNT=$((FAIL_COUNT + 1)); } || echo "[PASS] No conflicts"
else
    echo "[WARN] Not a git repo"
fi

# File checks
echo ""
echo "--- File Checks ---"
[ -f .gitignore ] && grep -q "^\.env$" .gitignore && echo "[PASS] .env in .gitignore" || { echo "[FAIL] .gitignore issue"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

# GitLeaks with file paths
echo ""
echo "--- Secret Detection ---"
LEAKS=$(gitleaks detect --source . --no-git --report-format json --report-path /tmp/leaks.json 2>&1)
if [ -f /tmp/leaks.json ]; then
    # Check if JSON array has actual leaks (not just empty array [])
    LEAK_COUNT=$(cat /tmp/leaks.json | python3 -c "import json, sys; data = json.load(sys.stdin); print(len(data))" 2>/dev/null || echo "0")
    if [ "$LEAK_COUNT" -gt 0 ] 2>/dev/null; then
        echo "[FAIL] Secrets found in:"
        cat /tmp/leaks.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for leak in data:
    print(f'  {leak.get(\"File\", \"unknown\")}:{leak.get(\"StartLine\", \"?\")} - {leak.get(\"RuleID\", \"?\")}')
" 2>/dev/null || cat /tmp/leaks.json
        FAIL_COUNT=$((FAIL_COUNT + 1))
    else
        echo "[PASS] No secrets detected"
    fi
    rm -f /tmp/leaks.json
else
    echo "[PASS] No secrets detected"
fi

# Large files
echo ""
echo "--- Large Files ---"
LARGE=$(find . -type f -size +50M ! -path "*/.venv/*" ! -path "*/.git/*" 2>/dev/null)
[ -z "$LARGE" ] && echo "[PASS] No large files" || { echo "[FAIL] Large files:"; echo "$LARGE"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

echo ""
echo "=========================="
[ "$FAIL_COUNT" -eq 0 ] && { echo "✓ SAFE TO PUSH"; exit 0; } || { echo "✗ $FAIL_COUNT FAILURES"; exit 1; }
