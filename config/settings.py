import os
from pathlib import Path
import pandas as pd

# Load .env file if python-dotenv is available (local dev)
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
    "https://docs.google.com/spreadsheets/d/"
    "1JyxkS1T_GrkNm2O4EsgOhAqnWWjTA805VwFFZ3K2kUA"
    "/export?format=csv",
)

PAGE_TITLE = "CFO Revenue & BizDev Dashboard"

# ---------- Authentication ----------

APP_PASSWORD = os.environ.get("APP_PASSWORD", "hudson340b")
DEBUG_SKIP_PASSWORD = os.environ.get("DEBUG_SKIP_PASSWORD", "true").lower() == "true"

# ---------- Login Email Notifications ----------
LOGIN_EMAIL_ENABLED = os.environ.get("LOGIN_EMAIL_ENABLED", "true").lower() == "true"
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "alerts340b@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "txqk bplq sfto aema")
LOGIN_NOTIFY_FROM = os.environ.get("LOGIN_NOTIFY_FROM", "alerts340b@gmail.com")

# ---------- Users ----------

# Admins – full access to all data
_admin_csv = os.environ.get("ADMIN_EMAILS", "")
if _admin_csv:
    ADMIN_EMAILS = [e.strip() for e in _admin_csv.split(",") if e.strip()]
else:
    ADMIN_EMAILS = [
        "mo@ccrxpath.com",
        "os@radciti.com",
        "dzehner@hudsonregionalhospital.com",
        "rhodie.smith@hudsonregionalhealth.com",
        "ssaleem@hudsonregionalhospital.com",
        "plapas@hudsonregionalhospital.com",
        "sayeed@ccrxpath.com",
    ]

# BizDevs – scoped to their own doctors & scripts
_bizdev_raw = os.environ.get("BIZDEV_USERS", "")
if _bizdev_raw:
    BIZDEV_USERS: dict = {}
    for entry in _bizdev_raw.split("|"):
        parts = entry.strip().split(":")
        if len(parts) == 3:
            email, name, bizdev_name = parts
            BIZDEV_USERS[email.strip().lower()] = {
                "name": name.strip(),
                "bizdev_name": bizdev_name.strip(),
            }
else:
    BIZDEV_USERS = {
        "asiya.jaffe@hudsonregionalhealth.com": {
            "name": "Asiya Jaffe",
            "bizdev_name": "Jaffe, Asiya",
        },
        "amharper@hudsonregionalhospital.com": {
            "name": "Amy Harper",
            "bizdev_name": "Harper, Amy",
        },
        "aprilmary.holcomb@hudsonregionalhealth.com": {
            "name": "Mary Holcomb",
            "bizdev_name": "Holcomb, Mary",
        },
        "megan.callan@carepointhealth.org": {
            "name": "Megan Callan",
            "bizdev_name": "Callan, Megan",
        },
        "sayeed.shehab@hudsonregionalhealth.com": {
            "name": "Sayeed Shehab",
            "bizdev_name": "Shehab, Sayeed",
        },
    }

# Viewers – unofficial BizDevs scoped to specific doctors (by Prescriber Full Name)
# Each viewer sees only claims from the doctors listed in their "doctors" list.
# To add a viewer:
#   "email@example.com": {
#       "name": "Display Name",
#       "doctors": ["LastName, FirstName", "LastName2, FirstName2"],
#   },
VIEWER_USERS: dict = {
    # Example (uncomment and edit to add a viewer):
    # "viewer@example.com": {
    #     "name": "Jane Viewer",
    #     "doctors": ["Smith, John", "Jones, Mary"],
    # },
    # Example (uncomment and edit to add a viewer):
     "Mikell": {
         "name": "Mikell",
         "doctors": ["Opam, Osafradu "],
     },
     "elisha": {
         "name": "Elisha",
         "doctors": ["Blokh, Ilya", "Sanchez-Pena, Jose R.", "Goldman, Alan", "Tawil, Steve", "Jagdeo, Jared"],
     },
     "halmrose@gmail.com": {
         "name": "Hal M Rose",
         "doctors": ["Sylvain, Paul", "Becker, Gary Shawn"],
     },

}
