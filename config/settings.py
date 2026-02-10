import os
from pathlib import Path
import pandas as pd

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = BASE_DIR / "data_files"

CLAIMS_FILE = DATA_DIR / "claims_with_pricing_v3.csv"
GOUT_FILE = DATA_DIR / "HUMC 340b Gout Payment Summary.xlsx"

START_DATE = pd.Timestamp("2025-01-01")
SPRX_RATE = 0.30
EST_PAID_PER_INFUSION = 37_500

DOCTORS_SHEET_CSV = os.environ.get(
    "DOCTORS_SHEET_CSV",
    "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/export?format=csv",
)

PAGE_TITLE = "CFO Revenue & BizDev Dashboard"

# ---------- Authentication ----------

APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")
DEBUG_SKIP_PASSWORD = os.environ.get("DEBUG_SKIP_PASSWORD", "false").lower() == "true"

# ---------- Login Email Notifications ----------
LOGIN_EMAIL_ENABLED = os.environ.get("LOGIN_EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
LOGIN_NOTIFY_FROM = os.environ.get("LOGIN_NOTIFY_FROM", "")

# ---------- Users ----------

# Admins – full access to all data
_admin_csv = os.environ.get("ADMIN_EMAILS", "")
ADMIN_EMAILS = [e.strip() for e in _admin_csv.split(",") if e.strip()]

# BizDevs – scoped to their own doctors & scripts
# Env format: email:Display Name:BizDev Column Name|email2:Name2:Column2
_bizdev_raw = os.environ.get("BIZDEV_USERS", "")
BIZDEV_USERS: dict = {}
for entry in _bizdev_raw.split("|"):
    parts = entry.strip().split(":")
    if len(parts) == 3:
        email, name, bizdev_name = parts
        BIZDEV_USERS[email.strip().lower()] = {
            "name": name.strip(),
            "bizdev_name": bizdev_name.strip(),
        }
