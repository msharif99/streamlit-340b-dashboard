import pandas as pd
import streamlit as st
from config.settings import GOUT_FILE, SPRX_RATE

@st.cache_data
def load_gout():
    df = pd.read_excel(GOUT_FILE, sheet_name="340 B")
    df.columns = df.columns.str.strip()

    df = df.rename(columns={
        "Service Date": "Date",
        "Reimbursement": "Paid",
        "Number of Infusions": "Infusions",
    })

    if "SPRX Paid" not in df.columns:
        df["SPRX Paid"] = 0.0

    # Drop summary/blank rows (no patient name)
    df = df[df["Patient"].notna()].copy()

    # Parse date ranges and multi-date strings, fall back to Paid Date
    def parse_date(val):
        s = str(val).strip()
        if s in ("nan", "NaT", ""):
            return pd.NaT
        result = pd.to_datetime(s, errors="coerce")
        if pd.notna(result):
            return result
        # Range like "5/15/2025-5/31/2025" → take end date
        if "/" in s and "-" in s:
            end = s.rsplit("-", 1)[-1].strip()
            result = pd.to_datetime(end, errors="coerce")
            if pd.notna(result):
                return result
        # Space-separated like "7/1/2025 7/15 7/29" → infer year from first, use last
        if " " in s:
            parts = s.split()
            first_dt = pd.to_datetime(parts[0], errors="coerce")
            if pd.notna(first_dt) and str(first_dt.year) in parts[0]:
                result = pd.to_datetime(f"{parts[-1]}/{first_dt.year}", errors="coerce")
                if pd.notna(result):
                    return result
        return pd.NaT

    df["Date"] = df["Date"].apply(parse_date)
    # Fall back to Paid Date where Service Date couldn't be parsed
    if "Paid Date" in df.columns:
        fallback = df["Date"].isna()
        df.loc[fallback, "Date"] = pd.to_datetime(df.loc[fallback, "Paid Date"], errors="coerce")

    for col in ["Paid", "SPRX Paid"]:
        df[col] = (
            df[col].astype(str)
            .str.replace(r"[\$,]", "", regex=True)
            .astype(float)
            .fillna(0)
        )

    df["Infusions"] = pd.to_numeric(df["Infusions"], errors="coerce").fillna(0)

    daily = df.groupby("Date").sum(numeric_only=True).sort_index()
    daily["Cumulative Cash"] = daily["Paid"].cumsum()
    daily["Cumulative SPRX Paid"] = daily["SPRX Paid"].cumsum()
    daily["SPRX Earned"] = daily["Cumulative Cash"] * SPRX_RATE
    daily["Cumulative Infusions"] = daily["Infusions"].cumsum()

    return daily

