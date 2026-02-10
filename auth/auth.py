import os
import smtplib
import threading
from datetime import datetime
from email.mime.text import MIMEText

import streamlit as st

from config.settings import (
    ADMIN_EMAILS,
    APP_PASSWORD,
    BIZDEV_USERS,
    DEBUG_SKIP_PASSWORD,
    LOGIN_EMAIL_ENABLED,
    LOGIN_NOTIFY_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
)


def _runtime_secret(key: str, fallback):
    """Read a secret at runtime — checks st.secrets (available on Streamlit
    Cloud after the runtime starts) then falls back to the settings.py value."""
    try:
        if key in st.secrets:
            val = str(st.secrets[key])
            if val.lower() in ("true", "false"):
                return val.lower() == "true"
            return val
    except Exception:
        pass
    return fallback


def _get_admin_emails():
    """Get admin emails, checking st.secrets at runtime."""
    try:
        if "ADMIN_EMAILS" in st.secrets:
            raw = str(st.secrets["ADMIN_EMAILS"])
            return [e.strip() for e in raw.split(",") if e.strip()]
    except Exception:
        pass
    return ADMIN_EMAILS


def _get_bizdev_users():
    """Get bizdev users, checking st.secrets at runtime."""
    try:
        if "BIZDEV_USERS" in st.secrets:
            raw = str(st.secrets["BIZDEV_USERS"])
            users = {}
            for entry in raw.split("|"):
                parts = entry.strip().split(":")
                if len(parts) == 3:
                    email, name, bizdev_name = parts
                    users[email.strip().lower()] = {
                        "name": name.strip(),
                        "bizdev_name": bizdev_name.strip(),
                    }
            return users
    except Exception:
        pass
    return BIZDEV_USERS


def _resolve_user(email: str):
    """Return a user dict if the email is authorised, else None."""
    email_lower = email.strip().lower()

    # Check admin list (runtime)
    admin_emails = _get_admin_emails()
    if email_lower in (e.lower() for e in admin_emails):
        return {"role": "admin", "name": "Admin", "email": email_lower}

    # Check bizdev list (runtime)
    bizdev_users = _get_bizdev_users()
    if email_lower in bizdev_users:
        info = bizdev_users[email_lower]
        return {
            "role": "bizdev",
            "name": info["name"],
            "bizdev_name": info["bizdev_name"],
            "email": email_lower,
        }

    return None


def _send_login_email(user: dict):
    """Send a login notification email to the user (runs in background thread)."""
    if not LOGIN_EMAIL_ENABLED:
        return

    to_email = user["email"]
    name = user.get("name", to_email)
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    body = (
        f"Hi {name},\n\n"
        f"Your 340B Dashboard account was just accessed on {now}.\n\n"
        f"If this wasn't you, please contact your administrator immediately.\n\n"
        f"— 340B Dashboard"
    )

    msg = MIMEText(body)
    msg["Subject"] = "340B Dashboard — Login Notification"
    msg["From"] = LOGIN_NOTIFY_FROM
    msg["To"] = to_email

    def _send():
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        except Exception:
            pass  # don't block login if email fails

    threading.Thread(target=_send, daemon=True).start()


def require_login():
    """Show a login form and block the app until the user authenticates.

    Returns the user dict on success, calls st.stop() otherwise.
    """
    if st.session_state.get("authenticated"):
        return st.session_state["user"]

    st.title("340B Dashboard Login")

    # Read at runtime so Streamlit Cloud secrets are available
    skip_pw = _runtime_secret("DEBUG_SKIP_PASSWORD", DEBUG_SKIP_PASSWORD)
    app_pw = _runtime_secret("APP_PASSWORD", APP_PASSWORD)

    with st.form("login_form"):
        email = st.text_input("Email address")
        if not skip_pw:
            password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if submitted:
        user = _resolve_user(email)
        if user is None:
            st.error("This email is not authorised to access the dashboard.")
        elif not skip_pw and password != app_pw:
            st.error("Incorrect password.")
        else:
            st.session_state["authenticated"] = True
            st.session_state["user"] = user
            _send_login_email(user)
            st.rerun()

    st.stop()


def logout_button():
    """Render a logout button in the sidebar."""
    if st.sidebar.button("Log out"):
        for key in ("authenticated", "user"):
            st.session_state.pop(key, None)
        st.rerun()
