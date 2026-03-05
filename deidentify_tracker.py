#!/usr/bin/env python3
"""
deidentify_tracker.py

Reads CCRx Onboarding.xlsx from ~/Downloads, extracts the IM2 sheet,
de-identifies patient names (initials only), removes phone numbers,
and saves to data_files/im2_tracker.csv.

Run automatically by run.sh --commit, or manually:
    python3 deidentify_tracker.py
"""

import sys
from pathlib import Path

import pandas as pd

SRC = Path.home() / "Downloads" / "CCRx Onboarding.xlsx"
DEST = Path(__file__).resolve().parent / "data_files" / "im2_tracker.csv"
SHEET = "IM2"


def initials(name: str) -> str:
    """'Thomas Chavis' → 'T.C.'"""
    parts = str(name).strip().split()
    return ".".join(p[0].upper() for p in parts if p) + "." if parts else ""


def main():
    if not SRC.exists():
        print(f"  ⚠ File not found: {SRC}")
        print("    Download CCRx Onboarding.xlsx to ~/Downloads and try again.")
        sys.exit(1)

    df = pd.read_excel(SRC, sheet_name=SHEET)

    # De-identify: initials only for patient name
    if "Patient Name" in df.columns:
        df["Patient Name"] = df["Patient Name"].apply(
            lambda x: initials(x) if pd.notna(x) and str(x).strip() else ""
        )

    # Remove PHI columns
    for col in ["Phone Number", "Patient DOB"]:
        if col in df.columns:
            df.drop(columns=col, inplace=True)

    # Clean up multiline cells
    for col in ["Medication", "Insurance Type", "Insight Team Notes", "Tracking Number"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.replace("\n", " | ").str.strip()

    # Drop rows with no meaningful data
    df = df[df["Patient Name"].astype(str).str.strip() != ""]

    df.to_csv(DEST, index=False)
    print(f"  ✓ im2_tracker.csv — {len(df)} patients written to {DEST}")


if __name__ == "__main__":
    main()
