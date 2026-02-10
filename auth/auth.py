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
    VIEWER_USERS,
)


def _resolve_user(email: str):
    """Return a user dict if the email is authorised, else None."""
    email_lower = email.strip().lower()

    # Check admin list
    if email_lower in (e.lower() for e in ADMIN_EMAILS):
        return {"role": "admin", "name": "Admin", "email": email_lower}

    # Check bizdev list
    if email_lower in BIZDEV_USERS:
        info = BIZDEV_USERS[email_lower]
        return {
            "role": "bizdev",
            "name": info["name"],
            "bizdev_name": info["bizdev_name"],
            "email": email_lower,
        }

    # Check viewer list (unofficial BizDev scoped to specific doctors)
    if email_lower in VIEWER_USERS:
        info = VIEWER_USERS[email_lower]
        return {
            "role": "viewer",
            "name": info["name"],
            "doctors": info["doctors"],
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

    with st.form("login_form"):
        email = st.text_input("Email address")
        if not DEBUG_SKIP_PASSWORD:
            password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if submitted:
        user = _resolve_user(email)
        if user is None:
            st.error("This email is not authorised to access the dashboard.")
        elif not DEBUG_SKIP_PASSWORD and password != APP_PASSWORD:
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
