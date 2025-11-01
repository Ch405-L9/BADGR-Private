#!/usr/bin/env bash
# BADGR_BOT · R10 staged driver (correct logical order)
set -Eeuo pipefail

cd "$(dirname "$0")/.."
stage="${1:-all}"
SHN_ID="${2:-BADGR_BOT-R10-StagedPilot-$(date -u +%F)T}"

# Source paths
source "$(dirname "$0")/../configs/paths.env" 2>/dev/null || {
    export BADGR_BASE="$(pwd)"
    export MANIFEST_YAML="${BADGR_BASE}/configs/manifest.yaml"
    export DOMAINS_FILE="${BADGR_BASE}/configs/domains.txt"
    export OUT_BASE="${BADGR_BASE}/outputs"
}

activate() { [[ -f .venv/bin/activate ]] && . .venv/bin/activate || true; }
ensure_dirs() { mkdir -p outputs/{contacts,enriched,lighthouse,logs,csv}; }
ok() { echo "[ok] $*"; }
warn() { echo "[warn] $*" >&2; }
need() { [[ -f "$1" ]] || { echo "[need] missing $1" >&2; return 1; }; }

run_discover() {
    activate; ensure_dirs
    
    if [[ ! -f "$MANIFEST_YAML" ]]; then
        warn "Missing $MANIFEST_YAML; skipping discovery"
        return 0
    fi
    
    echo "🔍 [discover] Starting discovery phase..."
    
    # Load env vars if .env exists
    [[ -f .env ]] && set -a && source .env && set +a
    
    python3 scripts/discover.py \
        --config "$MANIFEST_YAML" \
        --output "$DOMAINS_FILE" \
        --provider "${DISC_PROVIDER:-all}" \
        --max-results "${DISC_MAX_RESULTS:-25}" \
        ${VERBOSE:+--verbose} \
        || { warn "Discovery failed; check logs"; return 1; }
    
    local count=$(wc -l < "$DOMAINS_FILE" 2>/dev/null || echo 0)
    ok "Discovery complete ($count domains) → $DOMAINS_FILE"
}

run_collect_emails() {
    activate; ensure_dirs
    if need "${CONTACTS_CSV:-outputs/contacts/contacts.csv}"; then
        ok "contacts present ($(wc -l < "${CONTACTS_CSV}" 2>/dev/null || echo 0) lines)"
    else
        warn "collector must run before this driver"
    fi
}

run_emails_to_urls() {
    activate; ensure_dirs
    bash scripts/email_to_urls.sh
}

run_enrich() {
    activate; ensure_dirs
    if [[ -x scripts/enrich.sh ]]; then
        bash scripts/enrich.sh "${CONTACTS_CSV}" "${ENRICHED_CSV:-outputs/enriched/enriched.csv}" "upgini" "EMAIL" || true
    else
        python3 scripts/enrich_contacts.py \
            --input_path "${CONTACTS_CSV}" \
            --output_path "${ENRICHED_CSV:-outputs/enriched/enriched.csv}" \
            --provider upgini --search_keys EMAIL || true
    fi
}

run_lighthouse_last() {
    activate; ensure_dirs
    if [[ -x scripts/run.sh ]]; then
        bash scripts/run.sh || true
    else
        python3 -m src.main || true
    fi
}

run_cwv_analyze() {
    activate
    [[ -f scripts/analyze_cwv.py ]] && python3 scripts/analyze_cwv.py || ok "analyzer optional, skipping"
}

run_autodoc() {
    activate
    if make -n autodoc >/dev/null 2>&1; then
        make autodoc || true
    else
        {
            echo "BADGR_BOT R10 Build Report"
            date -u
            echo "urls.txt: $([[ -f "${URLS_TXT:-outputs/urls.txt}" ]] && echo present || echo missing)"
            echo "lighthouse reports: $(ls -1 ${LIGHTHOUSE_DIR:-outputs/lighthouse}/*.report.json 2>/dev/null | wc -l | tr -d ' ')"
        } > "${OUT_BASE}/BUILD_REPORT.txt"
    fi
}

run_cleanup() {
    activate
    [[ -x scripts/repo_clean.sh ]] && bash scripts/repo_clean.sh || ok "no repo_clean.sh; skipped"
}

case "$stage" in
    0|discover)              run_discover ;;
    1|collect_emails)        run_collect_emails ;;
    2|emails_to_urls)        run_emails_to_urls ;;
    3|enrich_contacts)       run_enrich ;;
    4|lighthouse_audit_last) run_lighthouse_last ;;
    5|cwv_analyze)           run_cwv_analyze ;;
    6|autodoc)               run_autodoc ;;
    7|cleanup)               run_cleanup ;;
    all)
        run_discover
        run_collect_emails
        run_emails_to_urls
        run_enrich
        run_lighthouse_last
        run_cwv_analyze
        run_autodoc
        run_cleanup
        ;;
    *) 
        echo "usage: $0 {0..7|discover|collect_emails|emails_to_urls|enrich_contacts|lighthouse_audit_last|cwv_analyze|autodoc|cleanup|all} [SHN_ID]" >&2
        exit 64
        ;;
esac

# SHN stamp after any stage
python3 - <<PY
import json, os, glob, time

out = {
    "shn_id": os.environ.get("SHN_ID","BADGR_BOT-R10-StagedPilot"),
    "domains_present": os.path.exists("${DOMAINS_FILE}"),
    "domains_count": sum(1 for _ in open("${DOMAINS_FILE}","r")) if os.path.exists("${DOMAINS_FILE}") else 0,
    "urls_present": os.path.exists("${URLS_TXT:-outputs/urls.txt}"),
    "lh_reports": len(glob.glob("${LIGHTHOUSE_DIR}/*.report.json")),
    "cwv_summary_csv": os.path.exists("${OUT_BASE}/cwv_summary.csv"),
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
}

os.makedirs("${OUT_BASE}", exist_ok=True)
with open("${OUT_BASE}/shn_stamp.json","w",encoding="utf-8") as f: 
    json.dump(out,f,indent=2)
print("[stamp] ${OUT_BASE}/shn_stamp.json updated")
PY
