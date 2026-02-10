import pandas as pd
import streamlit as st
from config.settings import GOUT_FILE, SPRX_RATE

@st.cache_data
def load_gout():
    df = pd.read_excel(GOUT_FILE)
    df.columns = df.columns.str.strip()

    df = df.rename(columns={
        "Last Service Date": "Date",
        "Paid Amount": "Paid",
        "Paid/Infusion" : "SPRX Paid",
        "# of Infusions": "Infusions",
    })

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

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

