import pandas as pd
import streamlit as st
from config.settings import CLAIMS_FILE, START_DATE
from data.phi import make_phi_safe

@st.cache_data
def load_claims():
    df = pd.read_csv(CLAIMS_FILE)
    df.columns = df.columns.str.strip().str.replace(r"\s+", " ", regex=True)

    df["Date"] = pd.to_datetime(df["Created On"], errors="coerce")
    df = df[df["Date"] >= START_DATE]
    df["Month"] = df["Date"].dt.to_period("M").astype(str)

    df["Dispensed Drug"] = (
        df["Dispensed Drug"].fillna("Unknown").astype(str).str.strip().str.title()
    )

    # Normalize Biz Dev column
    if "Marketer Name" in df.columns:
        df = df.rename(columns={"Marketer Name": "Biz Dev Name"})
    if "Biz Dev Name" not in df.columns:
        df["Biz Dev Name"] = "Unknown"
    df["Biz Dev Name"] = df["Biz Dev Name"].fillna("Unknown").astype(str).str.strip()

    for col in ["Total Price Paid", "WAC Price"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(r"[\$,]", "", regex=True)
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0.0

    if "Infusions" in df.columns:
        df["Infusions"] = pd.to_numeric(df["Infusions"], errors="coerce").fillna(1)
    else:
        df["Infusions"] = 1

    # Inventory type
    inv_cols = [c for c in df.columns if "inventory" in c.lower() or "340" in c.lower()]
    if inv_cols:
        df["Inventory_Type"] = df[inv_cols[0]].astype(str).str.lower().apply(
            lambda x: "340B" if "340" in x else "Rx"
        )
    else:
        df["Inventory_Type"] = "340B"

    # Revenue primitives
    df["Actual Revenue"] = df["Total Price Paid"]
    df["Potential Revenue (Raw)"] = 0.0
    df.loc[df["Total Price Paid"] == 0, "Potential Revenue (Raw)"] = df["WAC Price"]

    return df
