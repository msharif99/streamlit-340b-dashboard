#!/usr/bin/env bash
# run.sh — Launch the Streamlit dashboard, optionally commit & push data updates
#
# Usage:
#   ./run.sh                 # just run the dashboard
#   ./run.sh --commit        # commit updated data files to Git and push, then run
#   ./run.sh --commit-only   # commit and push without launching the dashboard

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Handle --commit / --commit-only flag ──
COMMIT=false
RUN_APP=true

for arg in "$@"; do
    case "$arg" in
        --commit)
            COMMIT=true
            ;;
        --commit-only)
            COMMIT=true
            RUN_APP=false
            ;;
    esac
done

if $COMMIT; then
    echo "── Checking for data changes ──"

    # Stage data files + dashboard code
    git add data_files/claims_with_pricing_v3.csv \
            "data_files/HUMC 340b Gout Payment Summary.xlsx" \
            data_files/npi_cache.json \
            dashboard_v6.py \
            app.py \
            config/settings.py

    # Only commit if there are staged changes
    if git diff --cached --quiet; then
        echo "No changes to commit."
    else
        git diff --cached --stat
        TIMESTAMP=$(date "+%Y-%m-%d %H:%M")
        git commit -m "Update data files ($TIMESTAMP)"
        echo ""
        echo "── Pushing to GitHub ──"
        git pull --rebase
        git push
        echo "── Done. Changes pushed to GitHub. ──"
    fi
fi

# ── Launch the dashboard ──
if $RUN_APP; then
    echo "── Starting Streamlit dashboard ──"
    streamlit run dashboard_v6.py
fi
