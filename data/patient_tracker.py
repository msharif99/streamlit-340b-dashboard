"""
Loader for CCRx Onboarding.xlsx — Patient Tracker.

Reads the four main sheets that share the IM2-style column format:
  PENDING, IM2, Non IM2, DiscontinueHold

Each sheet has:
  Date, Patient Name, Patient DOB, Medication, Telehealth Date,
  Phone Number, Insurance Type, Provider, Pharmacy, Status,
  Tracking Number, PA Key, PA Dates, Insight Team Notes, COPAY CARD
"""

import pandas as pd
import streamlit as st

from config.settings import PATIENT_TRACKER_FILE

_SHEETS = ["IM2", "PENDING", "Non IM2", "DiscontinueHold"]


@st.cache_data(show_spinner=False)
def load_patient_tracker() -> pd.DataFrame:
    """Return combined patient tracker DataFrame, or empty DF if file missing."""
    try:
        xl = pd.ExcelFile(PATIENT_TRACKER_FILE)
    except Exception:
        return pd.DataFrame()

    frames = []
    for sheet in _SHEETS:
        if sheet not in xl.sheet_names:
            continue
        try:
            df = pd.read_excel(xl, sheet_name=sheet)
            df["Sheet"] = sheet
            frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["Patient Name"].notna()].copy()

    combined["Date"] = pd.to_datetime(combined["Date"], errors="coerce")
    for col in ["Patient Name", "Status", "Provider", "Pharmacy"]:
        combined[col] = combined[col].fillna("").astype(str).str.strip()

    for col in ["Medication", "Insight Team Notes", "Insurance Type"]:
        combined[col] = (
            combined[col].fillna("").astype(str)
            .str.replace("\n", " | ").str.strip()
        )

    combined["Tracking Number"] = (
        combined["Tracking Number"].fillna("").astype(str)
        .str.replace("\n", " | ").str.strip()
    )

    return combined


def filter_tracker_by_doctors(df: pd.DataFrame, doctor_list: list) -> pd.DataFrame:
    """Return rows whose Provider fuzzy-matches any name in doctor_list."""
    if df.empty or not doctor_list:
        return df.iloc[0:0]

    def _words(s: str) -> set:
        return {w.lower().strip(".,") for w in str(s).split() if len(w) > 2}

    targets = [_words(d) for d in doctor_list]

    def matches(provider: str) -> bool:
        if not provider:
            return False
        pwords = _words(provider)
        return any(pwords & t for t in targets)

    return df[df["Provider"].apply(matches)].copy()
