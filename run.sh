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

# ── Known source paths for data files ──
GOUT_SRC="$HOME/Library/CloudStorage/GoogleDrive-amanatirfan3@gmail.com/My Drive/ThinkPad X1/340b/Operations/REPORTS/340 B.xlsx"
INSIGHT_SRC="$HOME/Library/CloudStorage/GoogleDrive-amanatirfan3@gmail.com/My Drive/ThinkPad X1/340b/Operations/REPORTS/Insight - CCRX Report All.xlsx"

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
    echo "── Syncing data files from source ──"

    # 340 B.xlsx — may be a symlink or already a real file; always pull latest from source
    if [ -f "$GOUT_SRC" ]; then
        rm -f "data_files/340 B.xlsx"
        cp "$GOUT_SRC" "data_files/340 B.xlsx"
        echo "  ✓ 340 B.xlsx"
    else
        echo "  ⚠ 340 B.xlsx source not found: $GOUT_SRC"
    fi

    # Insight CCRX Report — macOS alias can't be read by Python; copy real file
    if [ -f "$INSIGHT_SRC" ]; then
        cp "$INSIGHT_SRC" "data_files/Insight - CCRX Report All.xlsx"
        echo "  ✓ Insight - CCRX Report All.xlsx"
    else
        echo "  ⚠ Insight source not found: $INSIGHT_SRC"
    fi

    echo ""
    echo "── Checking for changes ──"

    # Stage data files + code
    git add \
        "data_files/340 B.xlsx" \
        "data_files/Insight - CCRX Report All.xlsx" \
        data_files/claims_with_pricing_v3.csv \
        "data_files/HUMC 340b Gout Payment Summary.xlsx" \
        app.py \
        dashboard_v6.py \
        config/settings.py \
        auth/auth.py \
        data/claims.py \
        data/insight.py \
        data/gout.py \
        run.sh 2>/dev/null || true

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
    streamlit run app.py
fi
