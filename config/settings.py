import os
from pathlib import Path
import pandas as pd

# Load .env file if python-dotenv is available (local dev)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_secret(key: str, default: str = "") -> str:
    """Read a config value from env vars first, then Streamlit secrets."""
    val = os.environ.get(key)
    if val is not None:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(key, default))
    except Exception:
        return default


BASE_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = BASE_DIR / "data_files"

CLAIMS_FILE = DATA_DIR / "claims_with_pricing_v3.csv"
GOUT_FILE = DATA_DIR / "HUMC 340b Gout Payment Summary.xlsx"

START_DATE = pd.Timestamp("2025-01-01")
SPRX_RATE = 0.30
EST_PAID_PER_INFUSION = 37_500

DOCTORS_SHEET_CSV = _get_secret(
    "DOCTORS_SHEET_CSV",
    "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/export?format=csv",
)

PAGE_TITLE = "CFO Revenue & BizDev Dashboard"

# ---------- Authentication ----------

APP_PASSWORD = _get_secret("APP_PASSWORD", "changeme")
DEBUG_SKIP_PASSWORD = _get_secret("DEBUG_SKIP_PASSWORD", "false").lower() == "true"

# ---------- Login Email Notifications ----------
LOGIN_EMAIL_ENABLED = _get_secret("LOGIN_EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST = _get_secret("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_get_secret("SMTP_PORT", "587"))
SMTP_USER = _get_secret("SMTP_USER", "")
SMTP_PASSWORD = _get_secret("SMTP_PASSWORD", "")
LOGIN_NOTIFY_FROM = _get_secret("LOGIN_NOTIFY_FROM", "")

# ---------- Users ----------

# Admins – full access to all data
_admin_csv = _get_secret("ADMIN_EMAILS", "")
ADMIN_EMAILS = [e.strip() for e in _admin_csv.split(",") if e.strip()]

# BizDevs – scoped to their own doctors & scripts
# Format: email:Display Name:BizDev Column Name|email2:Name2:Column2
_bizdev_raw = _get_secret("BIZDEV_USERS", "")
BIZDEV_USERS: dict = {}
for entry in _bizdev_raw.split("|"):
    parts = entry.strip().split(":")
    if len(parts) == 3:
        email, name, bizdev_name = parts
        BIZDEV_USERS[email.strip().lower()] = {
            "name": name.strip(),
            "bizdev_name": bizdev_name.strip(),
        }
