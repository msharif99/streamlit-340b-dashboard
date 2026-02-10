import pandas as pd
import streamlit as st
from config.settings import DOCTORS_SHEET_CSV

@st.cache_data(ttl=300)
def load_doctors():
    df = pd.read_csv(DOCTORS_SHEET_CSV)
    df.columns = (
        df.columns.str.lower().str.strip().str.replace(" ", "_")
    )
    return df

