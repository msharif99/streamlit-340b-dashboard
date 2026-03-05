"""
Loader and filtering utilities for the Insight - CCRX Report All.xlsx file.

The authoritative data is in the 'CCRX Providers Break Down' sheet which has
individual claim rows with actual remittance amounts.  The Score Card sheet
is a manual summary and is intentionally NOT used here.

Each data row contains:
  Date Filled, Drug, Prescriber Full Name (Last, First), Primary Remit Amount,
  Secondary Remit Amount, Patient Paid Amount, Acquisition Cost, Net Profit, etc.

Revenue  = Primary Remit + Secondary Remit + Patient Paid
Drug Cost = Acquisition Cost
"""

import pandas as pd
import streamlit as st

from config.settings import INSIGHT_FILE

_SHEET = "CCRX Providers Break Down "

# Embedded header strings that appear as data rows in the sheet
_JUNK_LABELS = {
    "Prescriber Full Name Last then First",
    "Dispensed Item Inventory Group",
}


def _normalize_name(name: str) -> set:
    """Return a lowercase word-set for fuzzy name matching.

    Handles 'Last, First', 'Last, First, MD', and 'First Last' formats.
    Credentials (MD, DPM, PA, etc.) are stripped so they don't pollute matching.
    """
    _credentials = {"md", "dpm", "pa", "np", "do", "phd", "rn", "dds", "dmd"}
    name = str(name).strip().lower()
    if "," in name:
        parts = name.split(",", 1)
        name = parts[1].strip() + " " + parts[0].strip()
    words = {w.strip(".,") for w in name.split()}
    return words - _credentials


@st.cache_data(show_spinner=False)
def load_insight() -> pd.DataFrame:
    """Load the Insight CCRX Providers Detail sheet into a clean DataFrame.

    Returns columns:
        Doctor        – normalized 'Last, First' name string
        Date          – pd.Timestamp of fill date
        Month         – 'YYYY-MM' period string
        Drug          – dispensed item name
        Inventory     – 340B / Rx / etc.
        Qty           – dispensed quantity
        Drug Cost     – acquisition cost
        Revenue       – Primary + Secondary + Patient remit
        Net Profit    – as reported
        Primary Remit – primary insurance paid
        Secondary Remit – secondary insurance paid
        Patient Paid  – patient copay

    Returns an empty DataFrame if the file is unavailable.
    """
    try:
        df = pd.read_excel(INSIGHT_FILE, sheet_name=_SHEET)
    except Exception:
        return pd.DataFrame(
            columns=[
                "Doctor", "Date", "Month", "Drug", "Inventory", "Qty",
                "Drug Cost", "Revenue", "Net Profit",
                "Primary Remit", "Secondary Remit", "Patient Paid",
            ]
        )

    # Drop rows with no prescriber (the vast majority are blank spacer rows)
    df = df[df["Prescriber Full Name Last then First"].notna()]
    # Drop embedded header rows
    df = df[~df["Prescriber Full Name Last then First"].isin(_JUNK_LABELS)]

    # Normalize doctor name to "Last, First" title-case, stripping credentials
    # so duplicates like "BRANDT, FREDERICK" and "Brandt, Frederick, MD" merge
    def _normalize_doctor(raw: str) -> str:
        raw = str(raw).strip().replace("\n", " ")
        parts = [p.strip() for p in raw.split(",")]
        # parts[0] = last name, parts[1] = first name, parts[2+] = credentials (drop)
        last = parts[0].title() if parts else ""
        first = parts[1].title() if len(parts) > 1 else ""
        return f"{last}, {first}" if first else last

    df["Doctor"] = df["Prescriber Full Name Last then First"].apply(_normalize_doctor)

    # Dates
    df["Date"] = pd.to_datetime(df["Date Filled"], errors="coerce")
    df["Month"] = df["Date"].dt.to_period("M").astype(str)

    # Numeric remit / cost columns
    for col in [
        "Primary Remit Amount",
        "Secondary Remit Amount",
        "Patient Paid Amount",
        "Acquisition Cost",
        "Net Profit",
        "Dispensed Quantity",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["Revenue"] = (
        df["Primary Remit Amount"]
        + df["Secondary Remit Amount"]
        + df["Patient Paid Amount"]
    )

    return df.rename(
        columns={
            "Dispensed Item Name": "Drug",
            "Dispensed Item Inventory Group": "Inventory",
            "Dispensed Quantity": "Qty",
            "Acquisition Cost": "Drug Cost",
            "Primary Remit Amount": "Primary Remit",
            "Secondary Remit Amount": "Secondary Remit",
            "Patient Paid Amount": "Patient Paid",
        }
    )[
        [
            "Doctor", "Date", "Month", "Drug", "Inventory", "Qty",
            "Drug Cost", "Revenue", "Net Profit",
            "Primary Remit", "Secondary Remit", "Patient Paid",
        ]
    ].copy()


def filter_insight_by_doctors(df: pd.DataFrame, doctor_list: list) -> pd.DataFrame:
    """Return only rows whose Doctor name matches one of the names in doctor_list.

    Matching is case-insensitive, credential-agnostic, and handles
    'Last, First' vs 'First Last' formats via 2-word intersection.
    """
    if not doctor_list:
        return df.iloc[0:0]

    target_sets = [_normalize_name(d) for d in doctor_list]

    def matches(doctor_name: str) -> bool:
        name_words = _normalize_name(doctor_name)
        return any(len(name_words & target) >= 2 for target in target_sets)

    return df[df["Doctor"].apply(matches)].copy()
