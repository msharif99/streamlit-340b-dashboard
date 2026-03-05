import streamlit as st
import pandas as pd
import pydeck as pdk
import plotly.graph_objects as go
from io import BytesIO

from auth.auth import require_login, logout_button
from config.settings import PAGE_TITLE, SPRX_RATE, EST_PAID_PER_INFUSION, INSIGHT_ADMIN_EMAILS, INSIGHT_BIZDEV_DOCTORS, VIEWER_USERS
from data.claims import load_claims
from data.gout import load_gout
from data.doctors import load_doctors
from data.filters import apply_user_scope, apply_claims_scope
from data.phi import make_phi_safe
from data.geocode import geocode_zips
from data.npi_lookup import lookup_doctor_locations
from data.insight import load_insight, filter_insight_by_doctors

from utils.ui import safe_top_n_slider

st.set_page_config(page_title=PAGE_TITLE, layout="wide")

# =========================
# AUTH
# =========================
user = require_login()
logout_button()

# =========================
# LOAD DATA
# =========================
df_all = load_claims()
daily_gout = load_gout()
doctors_raw = load_doctors()
doctors = apply_user_scope(doctors_raw, user)

df_scoped = apply_claims_scope(df_all, user)
df = df_scoped.copy()

# =========================
# HEADER
# =========================
st.markdown("# Hudson Regional Hospital")
st.caption(f"Logged in as: {user['name']} ({user['role']}) – {user['email']}")

# =========================
# INSIGHT PAGE ACCESS CHECK
# Admins: only those in INSIGHT_ADMIN_EMAILS
# BizDev: only if they have a doctors list assigned AND at least one matches Insight
# Viewer: only if at least one of their doctors matches Insight
#
# Doctor list is always re-resolved from current settings (not session state)
# so changes take effect immediately without requiring a logout.
# =========================
_insight_all = load_insight()
_role = user["role"]
_email = user["email"]

if _role == "admin":
    _show_insight = _email in (e.lower() for e in INSIGHT_ADMIN_EMAILS)
    _insight_doctor_list = []  # admins see all
elif _role == "bizdev":
    _insight_doctor_list = INSIGHT_BIZDEV_DOCTORS.get(_email, [])
    _show_insight = bool(_insight_doctor_list) and not filter_insight_by_doctors(_insight_all, _insight_doctor_list).empty
elif _role == "viewer":
    _insight_doctor_list = VIEWER_USERS.get(_email, {}).get("doctors", [])
    _show_insight = bool(_insight_doctor_list) and not filter_insight_by_doctors(_insight_all, _insight_doctor_list).empty
else:
    _insight_doctor_list = []
    _show_insight = False

# =========================
# SIDEBAR – page selector + shared filters
# =========================
st.sidebar.markdown("## Navigation")
_pages = ["340B Dashboard", "Financial Analysis", "Gout Program"]
if _show_insight:
    _pages.append("Insight Report")

page = st.sidebar.radio(
    "Page",
    _pages,
    label_visibility="collapsed",
)

st.sidebar.divider()
st.sidebar.header("Filters")

# Date range (shared by both pages)
min_date = df["Date"].min()
max_date = df["Date"].max()

if pd.isna(min_date) or pd.isna(max_date):
    st.warning("No data available.")
    st.stop()

min_dt = min_date.to_pydatetime()
max_dt = max_date.to_pydatetime()
today = pd.Timestamp.today().normalize()

date_preset = st.sidebar.selectbox(
    "Quick Date Range",
    ["Last 7 Days", "Last 30 Days", "Last Quarter", "Last Year", "Custom"],
    index=3,
)

if date_preset == "Last 7 Days":
    start_dt, end_dt = today - pd.Timedelta(days=7), today
elif date_preset == "Last 30 Days":
    start_dt, end_dt = today - pd.Timedelta(days=30), today
elif date_preset == "Last Quarter":
    start_dt, end_dt = today - pd.DateOffset(months=3), today
elif date_preset == "Last Year":
    start_dt, end_dt = today - pd.DateOffset(months=12), today
else:
    default_start = max_dt - pd.Timedelta(days=360)
    start_dt, end_dt = st.sidebar.slider(
        "Custom Date Range",
        min_value=min_dt,
        max_value=max_dt,
        value=(default_start, max_dt),
        format="YYYY-MM-DD",
    )
    start_dt, end_dt = pd.Timestamp(start_dt), pd.Timestamp(end_dt)

date_range_label = f"Date Range: {start_dt.date()} to {end_dt.date()}"

# Date-filter claims
df = df[(df["Date"] >= start_dt) & (df["Date"] <= end_dt)]

cutoff_30d = today - pd.Timedelta(days=30)

# Potential revenue: only scripts within 30-day window (still recoverable)
df["Potential Revenue (Included)"] = 0.0
df.loc[
    (df["Total Price Paid"] == 0)
    & (df["WAC Price"] > 0)
    & (df["Date"] >= cutoff_30d),
    "Potential Revenue (Included)",
] = df["Potential Revenue (Raw)"]

# Unable-to-fill revenue: unfilled scripts older than 30 days (assumed lost)
df["Unable to Fill Revenue"] = 0.0
df.loc[
    (df["Total Price Paid"] == 0)
    & (df["WAC Price"] > 0)
    & (df["Date"] < cutoff_30d),
    "Unable to Fill Revenue",
] = df["Potential Revenue (Raw)"]

# Date-filter gout
daily_gout = daily_gout.loc[
    (daily_gout.index >= start_dt) & (daily_gout.index <= end_dt)
].copy()

# ============================================================
#  340B DASHBOARD PAGE
# ============================================================
if page == "340B Dashboard":

    st.markdown("## 340B Revenue & BizDev Dashboard")

    # --- 340B-specific sidebar controls ---
    bizdev_options = ["All"] + sorted(df["Biz Dev Name"].dropna().unique().tolist())
    selected_bizdev = st.sidebar.selectbox("Filter by Biz Dev", bizdev_options)

    st.sidebar.header("Display Options")
    include_potential = st.sidebar.checkbox(
        "Include Potential Revenue (WAC where Paid = $0)", value=True
    )

    top_n_bizdev = safe_top_n_slider("Top Biz Dev", count=df["Biz Dev Name"].nunique())
    top_n_med = safe_top_n_slider("Top Medications", count=df["Dispensed Drug"].nunique(), default=20)
    top_n_phys = safe_top_n_slider("Top Physicians", count=df["Prescriber Full Name"].nunique(), default=20)

    # --- Apply bizdev filter ---
    df_filtered = df.copy()
    if selected_bizdev != "All":
        df_filtered = df_filtered[df_filtered["Biz Dev Name"] == selected_bizdev]

    phi_safe_df = make_phi_safe(df.copy())

    # --- NPI lookups & doctor enrichment ---
    npi_col = next((c for c in doctors_raw.columns if "npi" in c.lower()), None)
    doctor_locs = pd.DataFrame()
    if npi_col:
        doctor_locs = lookup_doctor_locations(doctors_raw[npi_col])

    scripts_by_npi = pd.DataFrame(columns=["npi", "scripts", "revenue"])
    if npi_col and "Prescriber NPI" in df_filtered.columns:
        claims_npi = df_filtered.copy()
        claims_npi["_npi"] = claims_npi["Prescriber NPI"].dropna().astype(float).astype(int).astype(str)
        claims_npi["_rev"] = pd.to_numeric(
            claims_npi["Total Price Paid"].astype(str).str.replace(r"[\$,]", "", regex=True),
            errors="coerce",
        ).fillna(0)
        scripts_by_npi = (
            claims_npi.groupby("_npi", as_index=False)
            .agg(scripts=("Rx Number", "count"), revenue=("_rev", "sum"))
            .rename(columns={"_npi": "npi"})
        )

    doctors_enriched = doctors_raw.copy()
    if npi_col and not scripts_by_npi.empty:
        doctors_enriched["_npi_str"] = doctors_enriched[npi_col].dropna().astype(float).astype(int).astype(str)
        doctors_enriched = doctors_enriched.merge(scripts_by_npi, left_on="_npi_str", right_on="npi", how="left")
        doctors_enriched["scripts"] = doctors_enriched["scripts"].fillna(0).astype(int)
        doctors_enriched["revenue"] = doctors_enriched["revenue"].fillna(0)
        doctors_enriched["status"] = doctors_enriched["scripts"].apply(lambda x: "Active" if x > 0 else "No Scripts")
        doctors_enriched.drop(columns=["npi"], inplace=True, errors="ignore")
        doctors_enriched.rename(columns={"_npi_str": "npi"}, inplace=True)
    else:
        doctors_enriched["npi"] = doctors_enriched.get(npi_col, "")
        doctors_enriched["scripts"] = 0
        doctors_enriched["revenue"] = 0.0
        doctors_enriched["status"] = "No Scripts"

    if not doctor_locs.empty and "npi" in doctors_enriched.columns:
        npi_locs = doctor_locs[["npi", "city", "state"]].rename(columns={"city": "npi_city", "state": "npi_state"})
        doctors_enriched = doctors_enriched.merge(npi_locs, on="npi", how="left")
        doctors_enriched["npi_location"] = (
            doctors_enriched["npi_city"].fillna("") + ", " + doctors_enriched["npi_state"].fillna("")
        ).str.strip(", ")
        doctors_enriched.drop(columns=["npi_city", "npi_state"], inplace=True)
    else:
        doctors_enriched["npi_location"] = ""

    geo_claims = geocode_zips(df_filtered["Prescriber Zip Code"]).dropna(subset=["lat", "lon"])
    patients_by_zip = pd.DataFrame()
    if not geo_claims.empty:
        zip5 = df_filtered["Prescriber Zip Code"].dropna().astype(str).str[:5]
        patient_counts = (
            df_filtered.assign(zip5=zip5)
            .groupby("zip5", as_index=False)
            .agg(patients=("Patient Full Name", "nunique"), claims=("Rx Number", "count"), city=("Prescriber City", "first"), state=("Prescriber State", "first"))
        )
        geo_unique = geo_claims.drop_duplicates("zip5")
        patients_by_zip = patient_counts.merge(geo_unique[["zip5", "lat", "lon"]], on="zip5", how="inner")

    CARTO_LIGHT = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json"

    # =========================================================
    # 1. KPIs (with Fill Rate)
    # =========================================================
    actual_340b = df_filtered.loc[df_filtered["Inventory_Type"] == "340B", "Actual Revenue"].sum()
    potential_340b_inc = df_filtered.loc[df_filtered["Inventory_Type"] == "340B", "Potential Revenue (Included)"].sum()
    potential_340b = actual_340b + potential_340b_inc
    unable_to_fill_wac = df_filtered["Unable to Fill Revenue"].sum()
    num_scripts = int(df_filtered["Infusions"].sum())

    total_claims_n = len(df_filtered)
    paid_claims_n = int((df_filtered["Total Price Paid"] > 0).sum())
    fill_rate_pct = paid_claims_n / max(total_claims_n, 1) * 100
    unfilled_claims_n = total_claims_n - paid_claims_n
    unable_to_fill_n = int(
        ((df_filtered["Total Price Paid"] == 0) & (df_filtered["Date"] < cutoff_30d)).sum()
    )

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("340B Revenue (Actual)", f"${actual_340b:,.0f}")
    k2.metric("Potential Revenue (30-Day)", f"${potential_340b:,.0f}")
    k3.metric("# of Scripts", f"{num_scripts:,}")
    k4.metric("Fill Rate", f"{fill_rate_pct:.0f}%")
    k5.metric("Unfilled Scripts", f"{unfilled_claims_n:,}")

    # Unable-to-fill row
    if unable_to_fill_n > 0:
        st.caption(
            f"**Scripts Unable to Be Filled** (>30 days old): "
            f"**{unable_to_fill_n:,}** scripts — "
            f"**${unable_to_fill_wac:,.0f}** WAC value assumed lost"
        )

    st.divider()

    # =========================================================
    # 2. OPEN UNFILLED SCRIPTS (last 30 days)
    # =========================================================
    st.subheader("Open Unfilled Scripts (Last 30 Days)")
    st.caption(
        "Prescriptions from the past 30 days with Total Price Paid = $0. "
        "Currently sourced from claims_with_pricing_v3; "
        "additional contract-pharmacy files will be added."
    )

    # --- Actionability buckets ---
    ACTIONABLE_PRIORITIES = {
        "New Fill", "Pending Clinical Notes", "Pending Rx Clarification",
        "* Insurance Info Needed", "Pending Labs", "MD request sent for more info",
        "Pending Med", "Pending Hardcopy", "Pending Hardcopy + Med",
        "Pending Telehealth", "Pending Telehealth + Hardcopy + Med",
        "Pending communication w. PT", "LVM", "MD Sent Clarified Rx",
        "Pharmacist Check", "Pending 340B Review",
        "Pending Formulary Medication Change", "Need More Recent Labs/Notes",
        "MDO Initiate PA", "Electronic PA sent to MDO",
        "Scheduling", "Scheduling - Initial Assessment",
    }
    WAITING_PRIORITIES = {
        "PA Under Review", "Peer-to-Peer", "Pending Foundation Assistance",
        "Pending Financial Assistance or PAP", "Sent NJ PAAD Application",
        "Bridge",
    }
    LOST_PRIORITIES = {
        "PA Denied", "PT Refused", "MDO Canceled", "Switched Therapies",
        "Therapy Not Appropriate", "Plan Exclusion", "High Copay",
        "Retail Med", "* Maintenance to be put on hold",
    }
    TRANSFER_PRIORITIES = {"Transfer", "Approved - Transfer"}

    # Action guidance per Rx Priority
    ACTION_GUIDANCE = {
        "New Fill": "Ready to dispense — follow up with pharmacy to expedite. Confirm patient pickup/delivery.",
        "Pending Clinical Notes": "Call prescriber's office to get clinical notes submitted. Fax requests often get delayed — a phone call is faster.",
        "* Insurance Info Needed": "Contact the patient to collect updated insurance card. Check for secondary coverage.",
        "Pending Rx Clarification": "Prescriber needs to clarify Rx (dosage, qty, or directions). Call the office directly.",
        "Pending Labs": "Lab results needed before dispensing. Confirm labs are ordered; follow up on results.",
        "MD request sent for more info": "Request already sent to MD. Follow up by phone if no response within 48 hours.",
        "MD Sent Clarified Rx": "MD already responded — follow up with pharmacy to process the updated Rx.",
        "Pending Med": "Medication may be on backorder. Confirm ETA with pharmacy or check alternative NDC.",
        "Pending communication w. PT": "Patient needs to be reached for counseling or consent. Try calling at different times, or try text.",
        "LVM": "Voicemail was left. Call again at a different time of day. Try text or email if available.",
        "Pharmacist Check": "Awaiting pharmacist review. Ask pharmacy if there are clinical concerns to resolve.",
        "Pending 340B Review": "Awaiting 340B eligibility check. Expedite the internal review.",
        "Pending Formulary Medication Change": "Drug not on formulary. Contact prescriber to switch to a covered alternative.",
        "Need More Recent Labs/Notes": "Updated labs or notes required. Call prescriber's office to request.",
        "MDO Initiate PA": "Prior auth must be started by the prescriber. Call to confirm they've submitted it.",
        "Electronic PA sent to MDO": "PA was sent electronically. Confirm the office received it and is responding.",
        "Scheduling": "Patient needs to be scheduled. Coordinate the appointment.",
        "Scheduling - Initial Assessment": "Schedule the initial assessment before treatment can begin.",
        "Pending Hardcopy": "Physical Rx required. Contact prescriber's office to send it.",
        "Pending Hardcopy + Med": "Need both hardcopy Rx and medication. Contact prescriber and pharmacy.",
        "Pending Telehealth": "Patient needs a telehealth visit. Help schedule the appointment.",
        "Pending Telehealth + Hardcopy + Med": "Multiple steps: telehealth visit + hardcopy Rx + medication. Coordinate all three.",
    }

    def _classify(row):
        pri = row.get("Rx Priority", "")
        msg = str(row.get("Primary Claim Message", ""))
        if "M/I PHARMACY NUMBER" in msg.upper():
            return "Transfer Out (Rare Not In-Network)"
        if pri in ACTIONABLE_PRIORITIES:
            return "Actionable NOW"
        if pri in WAITING_PRIORITIES:
            return "Waiting on External"
        if pri in LOST_PRIORITIES:
            return "Likely Lost"
        if pri in TRANSFER_PRIORITIES:
            return "Transfer Out (Rare Not In-Network)"
        return "Other"

    unfilled_cutoff = today - pd.Timedelta(days=30)
    unfilled = df_scoped[
        (df_scoped["Date"] >= unfilled_cutoff)
        & (df_scoped["Total Price Paid"] == 0)
    ].copy()

    if unfilled.empty:
        st.info("No open unfilled scripts in the last 30 days.")
    else:
        unfilled["Days Open"] = (today - unfilled["Date"]).dt.days
        unfilled["Rx Priority"] = unfilled["Rx Priority"].fillna("Unknown")
        unfilled["Bucket"] = unfilled.apply(_classify, axis=1)

        # M/I PHARMACY NUMBER alert
        mi_pharmacy = unfilled[
            unfilled["Primary Claim Message"].fillna("").str.upper().str.contains("M/I PHARMACY NUMBER", na=False)
        ]
        if not mi_pharmacy.empty:
            st.warning(
                f"**Systemic issue: {len(mi_pharmacy)} scripts rejected for "
                f"\"M/I Pharmacy Number\"** (WAC ${mi_pharmacy['WAC Price'].sum():,.0f}).  \n"
                "These are transfer-outs — Rare is not in-network for these plans. "
                "Route to an in-network contract pharmacy to capture this revenue."
            )

        # Summary metrics
        actionable = unfilled[unfilled["Bucket"] == "Actionable NOW"]
        u1, u2, u3, u4, u5 = st.columns(5)
        u1.metric("Total Unfilled", f"{len(unfilled):,}")
        u2.metric("Actionable NOW", f"{len(actionable):,}")
        u3.metric("Actionable WAC", f"${actionable['WAC Price'].sum():,.0f}")
        u4.metric("Unique Patients", f"{unfilled['Patient Full Name'].nunique():,}")
        u5.metric("Unique Prescribers", f"{unfilled['Prescriber Full Name'].nunique():,}")

        # Bucket chart
        bucket_summary = (
            unfilled.groupby("Bucket", as_index=False)
            .agg(Scripts=("Rx Number", "count"), WAC=("WAC Price", "sum"))
        )
        bucket_order = ["Actionable NOW", "Transfer Out (Rare Not In-Network)", "Waiting on External", "Likely Lost", "Other"]
        bucket_summary["_sort"] = bucket_summary["Bucket"].apply(lambda b: bucket_order.index(b) if b in bucket_order else 99)
        bucket_summary = bucket_summary.sort_values("_sort").drop(columns="_sort")

        BUCKET_COLORS = {
            "Actionable NOW": "#e74c3c",
            "Transfer Out (Rare Not In-Network)": "#f39c12",
            "Waiting on External": "#3498db",
            "Likely Lost": "#95a5a6",
            "Other": "#bdc3c7",
        }

        fig = go.Figure()
        for _, row in bucket_summary.iterrows():
            fig.add_bar(
                y=[row["Bucket"]], x=[row["Scripts"]], orientation="h",
                name=row["Bucket"],
                marker_color=BUCKET_COLORS.get(row["Bucket"], "#999"),
                text=[f"{row['Scripts']} (${row['WAC']:,.0f})"],
                textposition="outside", showlegend=False,
            )
        fig.update_layout(
            xaxis_title="Scripts", yaxis_title="",
            height=max(200, 50 * len(bucket_summary)),
            margin=dict(l=250, r=150, t=10, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- Actionable insights for BizDevs ---
        if not actionable.empty:
            with st.expander(f"**What to do: {len(actionable)} Actionable Scripts** — click for step-by-step guidance", expanded=True):
                actionable_sorted = actionable.sort_values("Days Open", ascending=False)
                for pri, grp in actionable_sorted.groupby("Rx Priority", sort=False):
                    guidance = ACTION_GUIDANCE.get(pri, "Follow up with pharmacy or prescriber's office.")
                    st.markdown(f"#### {pri}  ({len(grp)} scripts, ${grp['WAC Price'].sum():,.0f} WAC)")
                    st.info(f"**Next step:** {guidance}")
                    cols_to_show = [c for c in ["Days Open", "Dispensed Drug", "Prescriber Full Name", "Biz Dev Name", "WAC Price"] if c in grp.columns]
                    disp = grp[cols_to_show].copy()
                    if "WAC Price" in disp.columns:
                        disp["WAC Price"] = disp["WAC Price"].map("${:,.0f}".format)
                    st.dataframe(disp.sort_values("Days Open", ascending=False), use_container_width=True, hide_index=True)

        # Priority breakdown
        if "Rx Priority" in unfilled.columns:
            by_priority = (
                unfilled.groupby(["Bucket", "Rx Priority"], as_index=False)
                .agg(Scripts=("Rx Number", "count"), WAC_Total=("WAC Price", "sum"))
                .sort_values(["Bucket", "Scripts"], ascending=[True, False])
            )
            by_priority["WAC_Total"] = by_priority["WAC_Total"].map("${:,.0f}".format)
            show_priority_detail = st.checkbox("Show breakdown by Rx Priority", value=False)
            if show_priority_detail:
                st.dataframe(by_priority, use_container_width=True, height=min(400, 40 + 35 * len(by_priority)))

        # Full detail table
        unfilled_display_cols = [
            c for c in [
                "Days Open", "Date", "Bucket", "Rx Number", "Dispensed Drug",
                "Prescriber Full Name", "Prescriber NPI", "Biz Dev Name",
                "Primary Claim Status", "Rx Priority", "Primary Claim Message",
                "WAC Price", "340B Price",
            ] if c in unfilled.columns
        ]
        show_unfilled_detail = st.checkbox("Show Unfilled Scripts Detail", value=False)
        if show_unfilled_detail:
            st.dataframe(
                unfilled[unfilled_display_cols].sort_values("Days Open", ascending=False),
                use_container_width=True, height=400,
            )

        unfilled_export = make_phi_safe(unfilled.copy())
        st.download_button(
            "Download Unfilled Scripts (PHI-Safe CSV)",
            data=unfilled_export.to_csv(index=False).encode(),
            file_name="unfilled_scripts_last_30_days.csv", mime="text/csv",
        )

    st.divider()

    # =========================================================
    # 3. BIZ DEV SCORECARD
    # =========================================================
    st.subheader("Biz Dev Scorecard")

    bizdev_scorecard = (
        df_filtered.groupby("Biz Dev Name", as_index=False)
        .agg(
            Scripts=("Rx Number", "count"),
            Filled=("Total Price Paid", lambda x: (x > 0).sum()),
            Revenue=("Actual Revenue", "sum"),
            Unfilled_WAC=("Potential Revenue (Included)", "sum"),
        )
    )
    bizdev_scorecard["Fill Rate"] = bizdev_scorecard["Filled"] / bizdev_scorecard["Scripts"].clip(lower=1) * 100
    bizdev_scorecard["Unfilled"] = bizdev_scorecard["Scripts"] - bizdev_scorecard["Filled"]
    bizdev_scorecard = bizdev_scorecard.sort_values("Revenue", ascending=False).head(top_n_bizdev)

    bsc_disp = bizdev_scorecard[["Biz Dev Name", "Scripts", "Filled", "Unfilled", "Fill Rate", "Revenue", "Unfilled_WAC"]].copy()
    bsc_disp["Fill Rate"] = bsc_disp["Fill Rate"].map("{:.0f}%".format)
    bsc_disp["Revenue"] = bsc_disp["Revenue"].map("${:,.0f}".format)
    bsc_disp["Unfilled_WAC"] = bsc_disp["Unfilled_WAC"].map("${:,.0f}".format)
    bsc_disp = bsc_disp.rename(columns={"Unfilled_WAC": "Recoverable WAC (30d)"})
    st.dataframe(bsc_disp, use_container_width=True, height=min(400, 40 + 35 * len(bsc_disp)))

    by_rep = (
        df_filtered.groupby("Biz Dev Name", as_index=False)[["Actual Revenue", "Potential Revenue (Included)"]].sum()
    )
    by_rep["Total"] = by_rep["Actual Revenue"] + by_rep["Potential Revenue (Included)"]
    by_rep = by_rep.sort_values("Total", ascending=False).head(top_n_bizdev)

    show_table_bizdev = st.checkbox("Show Biz Dev Revenue Chart", value=False)
    if show_table_bizdev:
        fig = go.Figure()
        fig.add_bar(y=by_rep["Biz Dev Name"], x=by_rep["Actual Revenue"], orientation="h", name="Actual Revenue", text=by_rep["Actual Revenue"], texttemplate="$%{text:,.0f}", textposition="outside")
        if include_potential:
            fig.add_bar(y=by_rep["Biz Dev Name"], x=by_rep["Potential Revenue (Included)"], orientation="h", name="Potential Revenue", marker=dict(opacity=0.5))
        fig.update_layout(barmode="stack", xaxis_title="Revenue ($)", xaxis_tickformat="$,.0f", margin=dict(l=140, r=200, t=40, b=40))
        st.plotly_chart(fig, use_container_width=True)

    by_rep_export = by_rep.copy()
    by_rep_export.insert(0, "Date Range", date_range_label)
    st.download_button("Download Revenue by Biz Dev (CSV)", data=by_rep_export.to_csv(index=False).encode(), file_name=f"revenue_by_bizdev_{start_dt.date()}_to_{end_dt.date()}.csv", mime="text/csv")

    st.divider()

    # =========================================================
    # 4. CUMULATIVE 340B REVENUE
    # =========================================================
    st.subheader("Cumulative 340B Revenue Over Time")

    daily = (
        df_filtered.groupby("Date", as_index=False)
        .agg({"Actual Revenue": "sum", "Potential Revenue (Included)": "sum"})
        .sort_values("Date")
    )
    daily["Cumulative Actual"] = daily["Actual Revenue"].cumsum()
    daily["Cumulative Potential"] = daily["Potential Revenue (Included)"].cumsum()

    fig = go.Figure()
    fig.add_bar(x=daily["Date"], y=daily["Actual Revenue"], name="Actual Revenue (Paid)")
    if include_potential:
        fig.add_bar(x=daily["Date"], y=daily["Potential Revenue (Included)"], name="Potential Revenue", marker=dict(opacity=0.5))
    fig.add_scatter(x=daily["Date"], y=daily["Cumulative Actual"], mode="lines", name="Cumulative Actual", line=dict(width=3), yaxis="y2")
    if include_potential:
        fig.add_scatter(x=daily["Date"], y=daily["Cumulative Actual"] + daily["Cumulative Potential"], mode="lines", name="Cumulative + Potential", line=dict(dash="dot", width=3), yaxis="y2")
    fig.update_layout(
        barmode="stack", xaxis_title="Date", yaxis_title="Daily Revenue ($)", yaxis_tickformat="$,.0f",
        yaxis2=dict(title="Cumulative ($)", overlaying="y", side="right", tickformat="$,.0f"),
        legend=dict(orientation="h", y=-0.25),
    )
    st.plotly_chart(fig, use_container_width=True)

    # =========================================================
    # 5. 340B MONTHLY CASH
    # =========================================================
    st.subheader("340B – Monthly Cash Collected (Actual)")

    df_340b = df_filtered[df_filtered["Inventory_Type"] == "340B"].copy()
    monthly_340b = df_340b.groupby("Month", as_index=False)["Actual Revenue"].sum().sort_values("Month")

    fig = go.Figure()
    fig.add_bar(x=monthly_340b["Month"], y=monthly_340b["Actual Revenue"], name="340B Cash")
    fig.update_layout(xaxis_title="Month", yaxis_title="Cash ($)", yaxis_tickformat="$,.0f")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # =========================================================
    # 6. REVENUE BY MEDICATION
    # =========================================================
    st.subheader("Revenue by Medication")

    by_med = df_filtered.groupby("Dispensed Drug", as_index=False).agg({"Actual Revenue": "sum", "Potential Revenue (Included)": "sum"})
    by_med["Total"] = by_med["Actual Revenue"] + by_med["Potential Revenue (Included)"]
    by_med = by_med.sort_values("Total", ascending=False).head(top_n_med)

    show_table_med = st.checkbox("Show Medication Revenue Table", value=False)
    if show_table_med:
        st.caption(date_range_label)
        disp = by_med.copy()
        for c in ["Actual Revenue", "Potential Revenue (Included)", "Total"]:
            disp[c] = disp[c].map("${:,.0f}".format)
        st.dataframe(disp, use_container_width=True, height=300)

    fig = go.Figure()
    fig.add_bar(y=by_med["Dispensed Drug"], x=by_med["Actual Revenue"], orientation="h", name="Actual Revenue", text=by_med["Actual Revenue"], texttemplate="$%{text:,.0f}", textposition="outside")
    if include_potential:
        fig.add_bar(y=by_med["Dispensed Drug"], x=by_med["Potential Revenue (Included)"], orientation="h", name="Potential Revenue", marker=dict(opacity=0.45))
    fig.update_layout(barmode="stack", xaxis_title="Revenue ($)", xaxis_tickformat="$,.0f", height=max(400, 28 * len(by_med)))
    st.plotly_chart(fig, use_container_width=True)

    by_med_export = by_med.copy()
    by_med_export.insert(0, "Date Range", date_range_label)
    st.download_button("Download Revenue by Medication (CSV)", data=by_med_export.to_csv(index=False).encode(), file_name=f"revenue_by_medication_{start_dt.date()}_to_{end_dt.date()}.csv", mime="text/csv")

    st.divider()

    # =========================================================
    # 7. REVENUE BY PHYSICIAN (with Fill Rate)
    # =========================================================
    st.subheader("Revenue by Physician")

    by_phys = df_filtered.groupby("Prescriber Full Name", as_index=False).agg(
        **{
            "Actual Revenue": ("Actual Revenue", "sum"),
            "Potential Revenue (Included)": ("Potential Revenue (Included)", "sum"),
            "Scripts": ("Rx Number", "count"),
            "Filled": ("Total Price Paid", lambda x: (x > 0).sum()),
        }
    )
    by_phys["Total"] = by_phys["Actual Revenue"] + by_phys["Potential Revenue (Included)"]
    by_phys["Fill Rate"] = by_phys["Filled"] / by_phys["Scripts"].clip(lower=1) * 100
    by_phys = by_phys.sort_values("Total", ascending=False).head(top_n_phys)

    show_table_phys = st.checkbox("Show Physician Revenue Table", value=False)
    if show_table_phys:
        st.caption(date_range_label)
        disp = by_phys.copy()
        for c in ["Actual Revenue", "Potential Revenue (Included)", "Total"]:
            disp[c] = disp[c].map("${:,.0f}".format)
        disp["Fill Rate"] = disp["Fill Rate"].map("{:.0f}%".format)
        st.dataframe(disp, use_container_width=True, height=300)

    fig = go.Figure()
    fig.add_bar(y=by_phys["Prescriber Full Name"], x=by_phys["Actual Revenue"], orientation="h", name="Actual Revenue", text=by_phys["Actual Revenue"], texttemplate="$%{text:,.0f}", textposition="outside")
    if include_potential:
        fig.add_bar(y=by_phys["Prescriber Full Name"], x=by_phys["Potential Revenue (Included)"], orientation="h", name="Potential Revenue", marker=dict(opacity=0.45))
    fig.update_layout(barmode="stack", xaxis_title="Revenue ($)", xaxis_tickformat="$,.0f", height=max(400, 28 * len(by_phys)))
    st.plotly_chart(fig, use_container_width=True)

    by_phys_export = by_phys.copy()
    by_phys_export.insert(0, "Date Range", date_range_label)
    st.download_button("Download Revenue by Physician (CSV)", data=by_phys_export.to_csv(index=False).encode(), file_name=f"revenue_by_physician_{start_dt.date()}_to_{end_dt.date()}.csv", mime="text/csv")

    st.divider()

    # =========================================================
    # 8. DOCTORS ONBOARDED
    # =========================================================
    st.subheader("Doctors Onboarded")

    if "doctor_name" in doctors.columns:
        active_docs = int((doctors_enriched["status"] == "Active").sum())
        inactive_docs = int((doctors_enriched["status"] == "No Scripts").sum())
        total_docs = doctors["doctor_name"].nunique()

        d1, d2, d3 = st.columns(3)
        d1.metric("Total Doctors", total_docs)
        d2.metric("Sent Scripts", active_docs)
        d3.metric("No Scripts Yet", inactive_docs)

        if "pcc" in doctors.columns:
            docs_by_pcc = doctors.groupby("pcc").agg(doctors_count=("doctor_name", "nunique")).reset_index().sort_values("doctors_count", ascending=False)
            fig = go.Figure()
            fig.add_bar(y=docs_by_pcc["pcc"], x=docs_by_pcc["doctors_count"], orientation="h", text=docs_by_pcc["doctors_count"], textposition="outside")
            fig.update_layout(xaxis_title="Doctors Onboarded", yaxis_title="PCC (BizDev)", height=max(300, 28 * len(docs_by_pcc)))
            st.plotly_chart(fig, use_container_width=True)

        show_doc_table = st.checkbox("Show Doctors Table", value=False)
        if show_doc_table:
            disp_cols = [c for c in ["doctor_name", "npi", "npi_location", "specialty", "pcc", "scripts", "revenue", "status"] if c in doctors_enriched.columns]
            doc_display = doctors_enriched[disp_cols].copy()
            if "doctor_name" in doc_display.columns:
                doc_display = doc_display[doc_display["doctor_name"].notna()]
            if "revenue" in doc_display.columns:
                doc_display["revenue"] = doc_display["revenue"].map("${:,.0f}".format)
            doc_display = doc_display.sort_values("scripts", ascending=False)
            st.dataframe(
                doc_display.style.apply(lambda row: ["background-color: #9ca3af" if row.get("status") == "No Scripts" else "" for _ in row], axis=1),
                use_container_width=True, height=400,
            )
            st.caption("Grey rows = doctors who have not sent any scripts yet  |  NPI Location = practice address from CMS NPI Registry")
    else:
        st.metric("Total Doctors", int(doctors["doctors"].sum()))
        st.dataframe(doctors, use_container_width=True)

    st.divider()

    # =========================================================
    # 9. MAP: DOCTORS + SCRIPTS
    # =========================================================
    st.subheader("Doctor Locations & Script Activity")
    MAP_CONTROLS = "**Scroll** = zoom  |  **Click + drag** = pan  |  **Ctrl + drag** = rotate & tilt  |  **Hover** for details"
    st.caption(MAP_CONTROLS)

    if not doctor_locs.empty:
        doc_with_scripts = doctor_locs.copy()
        if not scripts_by_npi.empty:
            doc_with_scripts = doc_with_scripts.merge(scripts_by_npi, on="npi", how="left")
            doc_with_scripts["scripts"] = doc_with_scripts["scripts"].fillna(0).astype(int)
            doc_with_scripts["revenue"] = doc_with_scripts["revenue"].fillna(0)
        else:
            doc_with_scripts["scripts"] = 0
            doc_with_scripts["revenue"] = 0.0

        doc_by_zip = doc_with_scripts.groupby("zip", as_index=False).agg(
            lat=("lat", "first"), lon=("lon", "first"), doctors=("npi", "count"),
            total_scripts=("scripts", "sum"), total_revenue=("revenue", "sum"),
            city=("city", "first"), state=("state", "first"),
            names=("name", lambda x: "<br/>".join(x[:5]) + ("<br/>..." if len(x) > 5 else "")),
        )
        doc_by_zip["r"] = doc_by_zip["total_scripts"].apply(lambda x: 30 if x > 0 else 230)
        doc_by_zip["g"] = doc_by_zip["total_scripts"].apply(lambda x: 130 if x > 0 else 60)
        doc_by_zip["b"] = doc_by_zip["total_scripts"].apply(lambda x: 230 if x > 0 else 60)
        doc_by_zip["height"] = doc_by_zip["doctors"] + doc_by_zip["total_scripts"]

        mid_lat, mid_lon = 40.7440, -74.0324  # Hoboken, NJ
        deck = pdk.Deck(
            layers=[pdk.Layer("ColumnLayer", data=doc_by_zip, get_position=["lon", "lat"], get_elevation="height", elevation_scale=3000, radius=3000, get_fill_color=["r", "g", "b", 200], pickable=True, auto_highlight=True)],
            initial_view_state=pdk.ViewState(latitude=mid_lat, longitude=mid_lon, zoom=7, pitch=45, bearing=0),
            tooltip={"html": "<b style='font-size:14px'>{city}, {state}</b><br/>Doctors: <b>{doctors}</b><br/>Scripts: <b>{total_scripts}</b><br/>Revenue: <b>${total_revenue}</b><br/><hr style='margin:4px 0'/>{names}", "style": {"backgroundColor": "#1a1a2e", "color": "white", "padding": "8px", "borderRadius": "6px"}},
            map_style=CARTO_LIGHT,
        )
        st.pydeck_chart(deck, height=550)
        st.caption(f"Blue = sent scripts  |  Red = no scripts yet  |  **{doc_by_zip['doctors'].sum():,}** doctors, **{int(doc_by_zip['total_scripts'].sum()):,}** scripts, **${doc_by_zip['total_revenue'].sum():,.0f}** revenue")
    else:
        st.info("No doctor location data available.")

    st.divider()

    # =========================================================
    # 10. MAP: PATIENT SERVICE AREAS
    # =========================================================
    st.subheader("Patient Service Areas")
    st.caption(MAP_CONTROLS)

    if not patients_by_zip.empty:
        p_mid_lat, p_mid_lon = 40.7440, -74.0324  # Hoboken, NJ
        patient_deck = pdk.Deck(
            layers=[pdk.Layer("ColumnLayer", data=patients_by_zip, get_position=["lon", "lat"], get_elevation="patients", elevation_scale=3000, radius=3000, get_fill_color="[50, 180, 100, 200]", pickable=True, auto_highlight=True)],
            initial_view_state=pdk.ViewState(latitude=p_mid_lat, longitude=p_mid_lon, zoom=7, pitch=45, bearing=0),
            tooltip={"html": "<b style='font-size:14px'>{city}, {state}</b><br/>Zip: {zip5}<br/>Unique Patients: <b>{patients}</b><br/>Total Claims: {claims}", "style": {"backgroundColor": "#1a3a1e", "color": "white", "padding": "8px", "borderRadius": "6px"}},
            map_style=CARTO_LIGHT,
        )
        st.pydeck_chart(patient_deck, height=550)
        st.caption(f"Green = patient service areas  |  **{patients_by_zip['patients'].sum():,}** unique patients across **{len(patients_by_zip)}** locations in **{patients_by_zip['state'].nunique()}** states")
    else:
        st.info("No patient location data for the current filter.")

    st.divider()

    # =========================================================
    # 11. CLAIM-LEVEL DETAIL
    # =========================================================
    st.subheader("Claim-Level Detail (Filtered, PHI-Safe)")
    st.caption("Patient identifiers are hidden on screen and removed from all downloads.")
    st.dataframe(phi_safe_df.sort_values("Date", ascending=False), use_container_width=True, height=450)

    export_claims = make_phi_safe(df_filtered.copy())
    st.download_button("Download Claims (PHI-Safe CSV)", data=export_claims.to_csv(index=False).encode(), file_name="claims_phi_safe.csv", mime="text/csv")

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        by_rep_export.to_excel(writer, sheet_name="By_Biz_Dev", index=False)
        by_med_export.to_excel(writer, sheet_name="By_Medication", index=False)
        by_phys_export.to_excel(writer, sheet_name="By_Physician", index=False)
        phi_safe_df.assign(**{"Date Range": date_range_label}).to_excel(writer, sheet_name="Claims", index=False)

    st.download_button(
        "Download Full Revenue Workbook (PHI-Safe Excel)",
        data=output.getvalue(),
        file_name=f"revenue_summary_{start_dt.date()}_to_{end_dt.date()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ============================================================
#  FINANCIAL ANALYSIS PAGE
# ============================================================
elif page == "Financial Analysis":

    st.markdown("## Financial Analysis — Month-by-Month Breakdown")

    # --- Build monthly summary from date-filtered dataset ---
    fa_df = df.copy()
    fa_paid = fa_df[fa_df["Total Price Paid"] > 0]
    fa_unpaid = fa_df[fa_df["Total Price Paid"] == 0]

    fa_months = sorted(fa_df["Month"].unique())
    fa_rows = []
    for m in fa_months:
        tp = fa_paid.loc[fa_paid["Month"] == m, "Total Price Paid"].sum()
        b340 = fa_paid.loc[fa_paid["Month"] == m, "340B Value"].sum() if "340B Value" in fa_paid.columns else 0
        spread = tp - b340
        wac = fa_unpaid.loc[fa_unpaid["Month"] == m, "WAC Value"].sum() if "WAC Value" in fa_unpaid.columns else 0
        fa_rows.append({"Month": m, "Total Price Paid": tp, "340B Value": b340, "Spread": spread, "WAC (Unfilled)": wac})

    fa_summary = pd.DataFrame(fa_rows)

    # Totals row
    fa_totals = fa_summary[["Total Price Paid", "340B Value", "Spread", "WAC (Unfilled)"]].sum()

    # Split 340B vs non-340B for clarity
    fa_paid_340b = fa_paid[fa_paid.get("Inventory_Type", "340B") == "340B"] if "Inventory_Type" in fa_paid.columns else fa_paid
    fa_340b_revenue = fa_paid_340b["Total Price Paid"].sum()
    fa_non340b_revenue = fa_totals["Total Price Paid"] - fa_340b_revenue

    # KPIs
    fk1, fk2, fk3, fk4, fk5 = st.columns(5)
    fk1.metric("Total Cash Collected (All)", f"${fa_totals['Total Price Paid']:,.0f}")
    fk2.metric("340B Revenue", f"${fa_340b_revenue:,.0f}")
    fk3.metric("340B Acquisition Cost", f"${fa_totals['340B Value']:,.0f}")
    fk4.metric("Spread (Profit)", f"${fa_totals['Spread']:,.0f}")
    fk5.metric("Unfilled WAC (Opportunity)", f"${fa_totals['WAC (Unfilled)']:,.0f}")

    if fa_non340b_revenue > 0:
        st.caption(
            f"Total Cash includes **${fa_340b_revenue:,.0f}** from 340B inventory "
            f"+ **${fa_non340b_revenue:,.0f}** from non-340B (regular Rx). "
            f"The 340B Dashboard page shows only the 340B portion."
        )

    st.divider()

    # ---- Monthly summary table ----
    st.subheader("Monthly Financial Summary")

    fa_display = fa_summary.copy()
    for c in ["Total Price Paid", "340B Value", "Spread", "WAC (Unfilled)"]:
        fa_display[c] = fa_display[c].map("${:,.0f}".format)
    st.dataframe(fa_display, use_container_width=True, hide_index=True)

    # ---- Stacked bar chart ----
    fig_fa = go.Figure()
    fig_fa.add_bar(
        x=fa_summary["Month"], y=fa_summary["340B Value"],
        name="340B Acquisition Cost", marker_color="#e74c3c",
    )
    fig_fa.add_bar(
        x=fa_summary["Month"], y=fa_summary["Spread"],
        name="Spread (Profit)", marker_color="#2ecc71",
    )
    fig_fa.add_scatter(
        x=fa_summary["Month"], y=fa_summary["WAC (Unfilled)"],
        mode="lines+markers", name="WAC Unfilled (Opportunity Cost)",
        line=dict(color="#f39c12", width=3, dash="dot"),
        yaxis="y2",
    )
    fig_fa.update_layout(
        barmode="stack",
        xaxis_title="Month",
        yaxis_title="Paid Claims ($)",
        yaxis_tickformat="$,.0f",
        yaxis2=dict(title="WAC Unfilled ($)", overlaying="y", side="right", tickformat="$,.0f"),
        legend=dict(orientation="h", y=-0.25),
        height=450,
    )
    st.plotly_chart(fig_fa, use_container_width=True)

    st.divider()

    # =========================================================
    # UNFILLED SCRIPTS BY RX PRIORITY (Past 3 Months, Deduplicated)
    # =========================================================
    st.subheader("Unfilled Scripts by Rx Priority (Past 3 Months)")
    st.caption(
        "Deduplicated: same patient + same drug + same month = counted once. "
        "Sorted by WAC value to highlight biggest revenue recovery opportunities."
    )

    # Dedup unfilled — use df_scoped (all dates) for 3-month lookback
    fa_unfilled_src = df_scoped[df_scoped["Total Price Paid"] == 0].copy()
    fa_unpaid_dedup = (
        fa_unfilled_src
        .sort_values("WAC Value" if "WAC Value" in fa_unfilled_src.columns else "WAC Price", ascending=False)
        .drop_duplicates(subset=["Patient Full Name", "Dispensed Drug", "Month"], keep="first")
    )

    dupes_removed = len(fa_unfilled_src) - len(fa_unpaid_dedup)
    if dupes_removed > 0:
        st.info(f"Removed **{dupes_removed}** duplicate entries (same patient + drug + month).")

    # Filter to past 3 months from today
    fa_cutoff = today - pd.DateOffset(months=3)
    fa_recent = fa_unpaid_dedup[fa_unpaid_dedup["Date"] >= fa_cutoff].copy()
    fa_recent["Rx Priority"] = fa_recent["Rx Priority"].fillna("Unknown")
    fa_recent_months = sorted(fa_recent["Month"].unique())

    if fa_recent.empty:
        st.info("No unfilled scripts in the past 3 months.")
    else:
        # Summary KPIs
        total_unfilled_scripts = len(fa_recent)
        total_unfilled_wac = fa_recent["WAC Value"].sum() if "WAC Value" in fa_recent.columns else 0
        uk1, uk2 = st.columns(2)
        uk1.metric("Deduplicated Unfilled Scripts", f"{total_unfilled_scripts:,}")
        uk2.metric("Total WAC at Risk", f"${total_unfilled_wac:,.0f}")

        # Build pivot: scripts + WAC by reason by month
        pivot_scripts = fa_recent.groupby(["Rx Priority", "Month"]).size().unstack(fill_value=0)
        wac_col = "WAC Value" if "WAC Value" in fa_recent.columns else "WAC Price"
        pivot_wac = fa_recent.groupby(["Rx Priority", "Month"])[wac_col].sum().unstack(fill_value=0)

        # Build display dataframe
        reason_rows = []
        for reason in pivot_scripts.index:
            row = {"Rx Priority": reason}
            for m in fa_recent_months:
                s = int(pivot_scripts.loc[reason, m]) if m in pivot_scripts.columns else 0
                w = pivot_wac.loc[reason, m] if m in pivot_wac.columns else 0
                row[f"{m} Scripts"] = s
                row[f"{m} WAC"] = w
            row["Total Scripts"] = int(pivot_scripts.loc[reason].sum())
            row["Total WAC"] = float(pivot_wac.loc[reason].sum())
            reason_rows.append(row)

        reason_df = pd.DataFrame(reason_rows).sort_values("Total WAC", ascending=False)

        # Display table with scripts and WAC
        display_cols = ["Rx Priority"]
        for m in fa_recent_months:
            display_cols.extend([f"{m} Scripts", f"{m} WAC"])
        display_cols.extend(["Total Scripts", "Total WAC"])

        reason_display = reason_df[display_cols].copy()
        for c in reason_display.columns:
            if "WAC" in c:
                reason_display[c] = reason_display[c].map("${:,.0f}".format)

        st.dataframe(reason_display, use_container_width=True, hide_index=True, height=min(600, 40 + 35 * len(reason_display)))

        # Horizontal bar chart: WAC by reason
        top_reasons = reason_df.head(15)
        fig_reasons = go.Figure()
        fig_reasons.add_bar(
            y=top_reasons["Rx Priority"],
            x=top_reasons["Total WAC"],
            orientation="h",
            marker_color="#e74c3c",
            text=top_reasons.apply(
                lambda r: f"{int(r['Total Scripts'])} scripts — ${r['Total WAC']:,.0f}", axis=1
            ),
            textposition="outside",
        )
        fig_reasons.update_layout(
            xaxis_title="WAC Value ($)",
            xaxis_tickformat="$,.0f",
            yaxis=dict(autorange="reversed"),
            height=max(400, 35 * len(top_reasons)),
            margin=dict(l=250, r=250, t=10, b=40),
            showlegend=False,
        )
        st.plotly_chart(fig_reasons, use_container_width=True)

        # Key observations
        st.subheader("Key Observations")
        top5 = reason_df.head(5)
        for _, row in top5.iterrows():
            pct_scripts = row["Total Scripts"] / total_unfilled_scripts * 100
            pct_wac = row["Total WAC"] / total_unfilled_wac * 100 if total_unfilled_wac > 0 else 0
            st.markdown(
                f"- **{row['Rx Priority']}**: {int(row['Total Scripts'])} scripts "
                f"({pct_scripts:.0f}% of volume) — **${row['Total WAC']:,.0f}** WAC "
                f"({pct_wac:.0f}% of value)"
            )

        # Transfers vs actionable
        transfer_reasons = {"Transfer", "Approved - Transfer"}
        transfer_scripts = int(reason_df[reason_df["Rx Priority"].isin(transfer_reasons)]["Total Scripts"].sum())
        transfer_wac = reason_df[reason_df["Rx Priority"].isin(transfer_reasons)]["Total WAC"].sum()
        pa_scripts = int(reason_df[reason_df["Rx Priority"].str.contains("PA |PA$", regex=True, na=False)]["Total Scripts"].sum())
        pa_wac = reason_df[reason_df["Rx Priority"].str.contains("PA |PA$", regex=True, na=False)]["Total WAC"].sum()

        st.markdown("---")
        st.markdown(
            f"**Transfers** (Transfer + Approved Transfer): "
            f"**{transfer_scripts}** scripts — **${transfer_wac:,.0f}** WAC leaving the pharmacy"
        )
        st.markdown(
            f"**PA-Related** (PA Denied + MDO Initiate PA + Electronic PA): "
            f"**{pa_scripts}** scripts — **${pa_wac:,.0f}** WAC tied up in prior auth"
        )

        # Download
        st.download_button(
            "Download Unfilled Analysis (CSV)",
            data=reason_display.to_csv(index=False).encode(),
            file_name="unfilled_by_reason_3mo.csv",
            mime="text/csv",
        )

    st.divider()

    # Download monthly summary
    fa_export = fa_summary.copy()
    totals_row = pd.DataFrame([{
        "Month": "TOTAL",
        "Total Price Paid": fa_totals["Total Price Paid"],
        "340B Value": fa_totals["340B Value"],
        "Spread": fa_totals["Spread"],
        "WAC (Unfilled)": fa_totals["WAC (Unfilled)"],
    }])
    fa_export = pd.concat([fa_export, totals_row], ignore_index=True)
    st.download_button(
        "Download Monthly Financial Summary (CSV)",
        data=fa_export.to_csv(index=False).encode(),
        file_name="monthly_financial_summary.csv",
        mime="text/csv",
    )


# ============================================================
#  GOUT PROGRAM PAGE
# ============================================================
elif page == "Gout Program":

    st.markdown("## Gout Infusion Program")

    if daily_gout.empty:
        st.info("No gout program data available for the selected date range.")
        st.stop()

    gout_cash_actual = daily_gout["Paid"].sum()
    gout_unpaid_inf = daily_gout.loc[daily_gout["Paid"] == 0, "Infusions"].sum()
    gout_cash_projected = gout_cash_actual + gout_unpaid_inf * EST_PAID_PER_INFUSION
    total_inf = daily_gout["Infusions"].sum()
    paid_inf = total_inf - gout_unpaid_inf
    rev_per_inf = gout_cash_actual / max(paid_inf, 1)

    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Cash Received", f"${gout_cash_actual:,.0f}")
    g2.metric("Projected Cash", f"${gout_cash_projected:,.0f}")
    g3.metric("Total Infusions", f"{int(total_inf):,}")
    g4.metric("Revenue / Paid Infusion", f"${rev_per_inf:,.0f}")

    st.divider()

    # Cumulative chart
    st.subheader("Cash Collected vs Projected")
    gout_df = daily_gout.copy().sort_index()
    gout_df["Daily Paid"] = gout_df["Paid"]
    gout_df["Projected Daily Cash"] = 0.0
    gout_df.loc[gout_df["Daily Paid"] == 0, "Projected Daily Cash"] = gout_df["Infusions"] * EST_PAID_PER_INFUSION
    last_actual_cash = gout_df["Cumulative Cash"].iloc[-1] if not gout_df.empty else 0
    gout_df["Projected Cash From Actual"] = last_actual_cash + gout_df["Projected Daily Cash"].cumsum()
    gout_df["Projected Cash Masked"] = gout_df["Projected Cash From Actual"].where(gout_df["Daily Paid"] == 0)

    fig = go.Figure()
    fig.add_bar(x=gout_df.index, y=gout_df["Infusions"], name="Infusions", yaxis="y", marker=dict(opacity=0.4))
    fig.add_scatter(x=gout_df.index, y=gout_df["Cumulative Cash"], mode="lines", name="Actual Cash", line=dict(color="blue", width=3), yaxis="y2")
    fig.add_scatter(x=gout_df.index, y=gout_df["Projected Cash Masked"], mode="lines", name="Projected Cash", line=dict(color="blue", dash="dash", width=3), yaxis="y2")
    fig.update_layout(
        xaxis_title="Date",
        yaxis=dict(title="Infusions", rangemode="tozero"),
        yaxis2=dict(title="Cumulative Cash ($)", overlaying="y", side="right", tickformat="$,.0f", rangemode="tozero"),
        legend=dict(orientation="h", y=-0.25),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Monthly cash
    st.subheader("Monthly Cash Collected")
    gout_monthly = (
        daily_gout.copy()
        .assign(Month=lambda x: x.index.to_period("M").astype(str))
        .groupby("Month", as_index=False)["Cumulative Cash"]
        .max()
    )
    gout_monthly["Monthly Cash"] = gout_monthly["Cumulative Cash"].diff().fillna(gout_monthly["Cumulative Cash"])

    fig = go.Figure()
    fig.add_bar(x=gout_monthly["Month"], y=gout_monthly["Monthly Cash"], name="Gout Cash")
    fig.update_layout(xaxis_title="Month", yaxis_title="Cash ($)", yaxis_tickformat="$,.0f")
    st.plotly_chart(fig, use_container_width=True)


# ============================================================
#  INSIGHT REPORT PAGE
# ============================================================
elif page == "Insight Report":

    st.markdown("## Insight Specialty Pharmacy — CCRX Report")

    # _insight_all already loaded at startup (cached); reuse it here
    if _insight_all.empty:
        st.error(
            "Insight report data is not available. "
            "Check that the file path is correct (set INSIGHT_FILE env var if needed)."
        )
        st.stop()

    # ── Scope data to user's doctor list (viewer / bizdev with doctors) or show all (admin) ──
    if _role in ("viewer", "bizdev"):
        insight_df = filter_insight_by_doctors(_insight_all, _insight_doctor_list)
        st.caption(f"Showing data for your {len(_insight_doctor_list)} assigned doctor(s).")
    else:
        insight_df = _insight_all

    # ── Chronological month order ──
    month_order = sorted(insight_df["Month"].dropna().unique().tolist())

    # ── Aggregate by Doctor + Month (each row in source = 1 script/claim) ──
    summary = (
        insight_df.groupby(["Doctor", "Month"], as_index=False)
        .agg(
            Scripts=("Doctor", "count"),
            Revenue=("Revenue", "sum"),
            Drug_Cost=("Drug Cost", "sum"),
        )
    )
    # Net Profit computed here — source column is unreliable (mostly $0)
    summary["Net_Profit"] = summary["Revenue"] - summary["Drug_Cost"]

    # ── KPIs ──
    total_scripts = int(summary["Scripts"].sum())
    total_revenue = summary["Revenue"].sum()
    total_drug_cost = summary["Drug_Cost"].sum()
    total_profit = summary["Net_Profit"].sum()
    num_doctors = insight_df["Doctor"].nunique()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Doctors", f"{num_doctors:,}")
    k2.metric("Total Scripts", f"{total_scripts:,}")
    k3.metric("Total Revenue", f"${total_revenue:,.0f}")
    k4.metric("Total Drug Cost", f"${total_drug_cost:,.0f}")
    k5.metric("Net Profit", f"${total_profit:,.0f}")

    st.divider()

    # ── Scripts pivot: rows = Doctor, columns = Month ──
    st.subheader("Scripts per Month")
    pivot_scripts = (
        summary.pivot_table(index="Doctor", columns="Month", values="Scripts", aggfunc="sum", fill_value=0)
        .reindex(columns=month_order, fill_value=0)
    )
    pivot_scripts["Total"] = pivot_scripts.sum(axis=1)
    pivot_scripts = pivot_scripts.sort_values("Total", ascending=False)
    st.dataframe(pivot_scripts, use_container_width=True)

    st.divider()

    # ── Revenue pivot: rows = Doctor, columns = Month ──
    st.subheader("Revenue per Month ($)")
    pivot_rev = (
        summary.pivot_table(index="Doctor", columns="Month", values="Revenue", aggfunc="sum", fill_value=0)
        .reindex(columns=month_order, fill_value=0)
    )
    pivot_rev["Total"] = pivot_rev.sum(axis=1)
    pivot_rev = pivot_rev.sort_values("Total", ascending=False)

    pivot_rev_display = pivot_rev.copy()
    for col in pivot_rev_display.columns:
        pivot_rev_display[col] = pivot_rev_display[col].apply(lambda x: f"${x:,.0f}")
    st.dataframe(pivot_rev_display, use_container_width=True)

    st.divider()

    # ── Revenue bar chart by doctor ──
    st.subheader("Total Revenue by Doctor")
    rev_by_doc = (
        summary.groupby("Doctor", as_index=False)
        .agg(Scripts=("Scripts", "sum"), Revenue=("Revenue", "sum"), Drug_Cost=("Drug_Cost", "sum"), Net_Profit=("Net_Profit", "sum"))
        .sort_values("Revenue", ascending=False)
    )

    fig_insight = go.Figure()
    fig_insight.add_bar(
        y=rev_by_doc["Doctor"],
        x=rev_by_doc["Revenue"],
        orientation="h",
        name="Revenue",
        text=rev_by_doc["Revenue"].apply(lambda x: f"${x:,.0f}"),
        textposition="outside",
    )
    fig_insight.add_bar(
        y=rev_by_doc["Doctor"],
        x=rev_by_doc["Drug_Cost"],
        orientation="h",
        name="Drug Cost",
        marker=dict(opacity=0.6),
    )
    fig_insight.update_layout(
        barmode="overlay",
        xaxis_title="Amount ($)",
        xaxis_tickformat="$,.0f",
        height=max(400, 28 * len(rev_by_doc)),
        margin=dict(l=160, r=200, t=30, b=40),
        legend=dict(orientation="h", y=-0.15),
    )
    st.plotly_chart(fig_insight, use_container_width=True)

    st.divider()

    # ── Download ──
    st.download_button(
        "Download Insight Report (CSV)",
        data=insight_df.to_csv(index=False).encode(),
        file_name="insight_ccrx_report.csv",
        mime="text/csv",
    )
