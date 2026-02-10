import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path

import streamlit as st
###
# CRITICAL - PHI Protection for any data export
####
def make_phi_safe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Removes ONLY direct patient identifiers.
    Keeps Biz Dev Name, Prescriber Name, and all operational fields.
    """
    PHI_COLUMNS_EXACT = {
        "Patient Full Name",
        "Patient Contact #",
        "Patient Phone",
        "Patient Phone #",
        "Patient Email",
        "Patient Address",
        "MRN",
        "Medical Record Number"
    }

    cols_to_drop = [c for c in df.columns if c.strip() in PHI_COLUMNS_EXACT]
    return df.drop(columns=cols_to_drop, errors="ignore")



# =========================
# ACCESS CONTROL – EMAIL GATE
# =========================

ALLOWED_DOMAINS = {
    "radciti.com",
    "ccrxpath.com",
    "hudsonregionalhospital.com",
}

ALLOWED_EMAILS = {
    # optional explicit overrides
    "ms@ccrxpath.com",
}

# Initialize session flag
if "access_granted" not in st.session_state:
    st.session_state["access_granted"] = False

#DEBUG OVERRIDE
st.session_state["access_granted"] = True

# Gate UI
if not st.session_state["access_granted"]:
    st.title("Access Verification Required")

    email = st.text_input(
        "Enter your work email to continue",
        placeholder="name@company.com"
    )

    if email:
        email = email.strip().lower()

        if "@" in email:
            domain = email.split("@")[-1]
        else:
            domain = ""

        if email in ALLOWED_EMAILS or domain in ALLOWED_DOMAINS:
            st.session_state["access_granted"] = True
            st.session_state["user_email"] = email
            st.success("Access granted. Welcome.")
            st.rerun()
        else:
            st.error(
                "Access denied. Please use an approved work email "
                "()."
            )

    st.stop()

st.caption(f"Logged in as: {st.session_state.get('user_email')}")

# =========================
# CONFIG
# =========================
START_DATE = pd.Timestamp("2025-01-01")
SPRX_RATE = 0.30

BASE_DIR = Path(__file__).resolve().parent
CLAIMS_FILE = "claims_with_pricing_v3.csv"
GOUT_EXCEL_FILE = "HUMC 340b Gout Payment Summary.xlsx"

# =========================
# LOAD CLAIMS DATA
# =========================
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

    # Normalize Biz Dev / Marketer column
    if "Marketer Name" in df.columns:
        df = df.rename(columns={"Marketer Name": "Biz Dev Name"})
    
    df["Biz Dev Name"] = (
        df["Biz Dev Name"].fillna("Unknown").astype(str).str.strip()
    )

    for col in ["Total Price Paid", "WAC Price"]:
        df[col] = (
            df[col].astype(str).str.replace(r"[\$,]", "", regex=True)
        )
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "Infusions" in df.columns:
        df["Infusions"] = pd.to_numeric(df["Infusions"], errors="coerce").fillna(1)
    else:
        df["Infusions"] = 1

    # Inventory Type (hardened)
    inventory_cols = [c for c in df.columns if "inventory" in c.lower() or "340" in c.lower()]
    if inventory_cols:
        col = inventory_cols[0]
        df["Inventory_Type"] = df[col].astype(str).str.lower().apply(
            lambda x: "340B" if "340" in x else "Rx"
        )
    else:
        df["Inventory_Type"] = "340B"

    # Revenue primitives
    df["Actual Revenue"] = df["Total Price Paid"]
    df["Potential Revenue (Raw)"] = 0.0
    df.loc[df["Total Price Paid"] == 0, "Potential Revenue (Raw)"] = df["WAC Price"]

    return df

# =========================
# LOAD GOUT DATA
# =========================
@st.cache_data
def load_gout_excel():
    df = pd.read_excel(GOUT_EXCEL_FILE)
    df.columns = df.columns.str.strip()

    df = df.rename(columns={
        "Created On": "Last Service Date",
        "Total Paid": "Paid Amount",
        "# of Infusions": "Infusions",
        "SPRX Paid": "SPRX Paid"
    })

    # Guarantee required columns
    for col, default in {
        "Paid Amount": 0.0,
        "Infusions": 0.0,
        "SPRX Paid": 0.0
    }.items():
        if col not in df.columns:
            df[col] = default

    df["Last Service Date"] = pd.to_datetime(df["Last Service Date"], errors="coerce")

    for col in ["Paid Amount", "SPRX Paid"]:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(r"[\$,]", "", regex=True)
        )
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["Infusions"] = pd.to_numeric(df["Infusions"], errors="coerce").fillna(0.0)

    daily = (
        df.groupby("Last Service Date", as_index=True)
        .agg({
            "Paid Amount": "sum",
            "SPRX Paid": "sum",
            "Infusions": "sum"
        })
        .sort_index()
    )

    daily["Cumulative Cash"] = daily["Paid Amount"].cumsum()
    daily["Cumulative SPRX Paid"] = daily["SPRX Paid"].cumsum()
    daily["SPRX Earned (30%)"] = daily["Cumulative Cash"] * SPRX_RATE
    daily["Cumulative Infusions"] = daily["Infusions"].cumsum()

    return daily

# =========================
# LOAD DATA
# =========================
df = load_claims()
daily_gout = load_gout_excel()

# -------------------------
# GUARANTEE POTENTIAL COLUMN + 30-DAY RULE
# -------------------------
cutoff_date = pd.Timestamp.today().normalize() - pd.Timedelta(days=360)

df["Potential Revenue (Included)"] = 0.0
df.loc[
    (df["Total Price Paid"] == 0) &
    (df["WAC Price"] > 0) &
    (df["Date"] >= cutoff_date),
    "Potential Revenue (Included)"
] = df["Potential Revenue (Raw)"]

st.markdown(
    """
    # Hudson Regional Hospital  
    ## 340B & Gout Infusion Revenue Dashboard
    """
)
# =========================
# SIDEBAR CONTROLS
# =========================

st.sidebar.header("Filters")

# -------------------------
# DATE RANGE PRESETS
# -------------------------
min_date = df["Date"].min()
max_date = df["Date"].max()

if pd.isna(min_date) or pd.isna(max_date):
    st.warning("No data available for selected filters.")
    st.stop()

min_dt = min_date.to_pydatetime()
max_dt = max_date.to_pydatetime()

default_start = max_dt - pd.Timedelta(days=360)
today = pd.Timestamp.today().normalize()

date_preset = st.sidebar.selectbox(
    "Quick Date Range",
    ["Last 7 Days", "Last 30 Days", "Last Quarter", "Last Year", "Custom"],
    index=1
)

# -------------------------
# RESOLVE DATE RANGE
# -------------------------
if date_preset == "Last 7 Days":
    start_dt = today - pd.Timedelta(days=7)
    end_dt = today

elif date_preset == "Last 30 Days":
    start_dt = today - pd.Timedelta(days=30)
    end_dt = today

elif date_preset == "Last Quarter":
    start_dt = today - pd.DateOffset(months=3)
    end_dt = today

elif date_preset == "Last Year":
    start_dt = today - pd.DateOffset(months=12)
    end_dt = today

else:  # Custom
    start_dt, end_dt = st.sidebar.slider(
        "Custom Date Range",
        min_value=min_dt,
        max_value=max_dt,
        value=(default_start, max_dt),
        format="YYYY-MM-DD"
    )
    start_dt = pd.Timestamp(start_dt)
    end_dt = pd.Timestamp(end_dt)

# =========================
# DATE RANGE LABEL (DISPLAY + EXPORT)
# =========================
date_range_label = f"Date Range: {start_dt.date()} to {end_dt.date()}"


# APPLY DATE FILTER TO 340B DATA (df)
df = df[(df["Date"] >= start_dt) & (df["Date"] <= end_dt)]
# =========================
# APPLY DATE FILTER TO GOUT DATA (daily_gout)
# =========================
daily_gout = daily_gout.loc[
    (daily_gout.index >= start_dt) &
    (daily_gout.index <= end_dt)
].copy()

# =========================
# PHI-SAFE DATASET (DISPLAY + EXPORT)
# =========================
phi_safe_df = make_phi_safe(df.copy())

bizdev_options = ["All"] + sorted(df["Biz Dev Name"].dropna().unique().tolist())

selected_bizdev = st.sidebar.selectbox(
    "Filter by Biz Dev",
    bizdev_options
)

df_filtered = df.copy()

if selected_bizdev != "All":
    df_filtered = df_filtered[df_filtered["Biz Dev Name"] == selected_bizdev]


#Show Gout Program or Not
st.sidebar.header("Program Visibility")

# =========================
# POTENTIAL REVENUE TOGGLE (LAST 30 DAYS ONLY)
# =========================
include_potential = st.sidebar.checkbox(
    "Include Potential Additional Revenue (WAC where Paid = $0, last 30 days)",
    value=True
)

show_gout = st.sidebar.checkbox(
    "Show Gout Program (KPIs & Charts)",
    value=True
)

# =========================
# GOUT KPI ROW (ACTUAL vs PROJECTED)
# =========================
if show_gout:
    st.subheader("Gout Program Snapshot")
    
    EST_PAID_PER_INFUSION = 37_500
    
    gout_cash_actual = daily_gout["Paid Amount"].sum()
    
    gout_unpaid_infusions = daily_gout.loc[
        daily_gout["Paid Amount"] == 0,
        "Infusions"
    ].sum()
    
    gout_cash_projected = gout_cash_actual + gout_unpaid_infusions * EST_PAID_PER_INFUSION
    
    total_infusions = daily_gout["Infusions"].sum()
    paid_infusions = total_infusions - gout_unpaid_infusions
    
    rev_per_inf = gout_cash_actual / max(paid_infusions, 1)
    
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Gout Cash Received", f"${gout_cash_actual:,.0f}")
    g2.metric("Gout Projected Cash", f"${gout_cash_projected:,.0f}")
    g3.metric("Total Infusions", f"{int(total_infusions):,}")
    g4.metric("Actual Revenue / Paid Infusion", f"${rev_per_inf:,.0f}")


# =========================
# 340B KPI ROW (ACTUAL vs POTENTIAL)
# =========================

actual_340b = df_filtered.loc[
    df_filtered["Inventory_Type"] == "340B",
    "Actual Revenue"
].sum()

potential_340b_1 = df_filtered.loc[
    df_filtered["Inventory_Type"] == "340B",
    "Potential Revenue (Included)"
].sum()

potential_340b = actual_340b + potential_340b_1

num_scripts = int(df_filtered["Infusions"].sum())
rev_per_script = actual_340b / max(num_scripts, 1)

k1, k2, k3, k4 = st.columns(4)
k1.metric("340B Revenue (Actual)", f"${actual_340b:,.0f}")
k2.metric("340B Revenue (Potential)", f"${potential_340b:,.0f}")
k3.metric("# of Scripts", f"{num_scripts:,}")
k4.metric("Actual Revenue / Script", f"${rev_per_script:,.0f}")


df_filtered["Potential Revenue (Included)"] = 0.0

df_filtered.loc[
    (df_filtered["Total Price Paid"] == 0) &
    (df_filtered["WAC Price"] > 0) &
    (df_filtered["Date"] >= cutoff_date),
    "Potential Revenue (Included)"
] = df_filtered["Potential Revenue (Raw)"]

df_filtered["Revenue_For_Charts"] = (
    df_filtered["Actual Revenue"] + df_filtered["Potential Revenue (Included)"]
    if include_potential
    else df_filtered["Actual Revenue"]
)

# Rolling 30-day cutoff (relative to today)
cutoff_date = pd.Timestamp.today().normalize() - pd.Timedelta(days=30)

# =========================
# GOUT – ACTUAL vs PROJECTED CASH (NON-OVERLAPPING, CONTINUOUS)
# =========================
if show_gout:
    st.subheader("Gout Program – Cash Collected vs Projected")
    
    EST_PAID_PER_INFUSION = 37_500
    
    gout_df = daily_gout.copy().sort_index()
    
    # -------------------------
    # DAILY ACTUAL PAID
    # -------------------------
    gout_df["Daily Paid"] = gout_df["Paid Amount"]
    
    # -------------------------
    # PROJECTED DAILY CASH (ONLY WHEN UNPAID)
    # -------------------------
    gout_df["Projected Daily Cash"] = 0.0
    gout_df.loc[
        gout_df["Daily Paid"] == 0,
        "Projected Daily Cash"
    ] = gout_df["Infusions"] * EST_PAID_PER_INFUSION
    
    # -------------------------
    # BASELINE = LAST ACTUAL CASH
    # -------------------------
    if gout_df.empty:
        last_actual_cash = 0.0
    else:
        last_actual_cash = gout_df["Cumulative Cash"].iloc[-1]

    
    # -------------------------
    # CUMULATIVE PROJECTED (CONTINUOUS FROM ACTUAL)
    # -------------------------
    gout_df["Projected Cash From Actual"] = (
        last_actual_cash + gout_df["Projected Daily Cash"].cumsum()
    )
    
    # -------------------------
    # MASK PROJECTED ON DAYS WITH ACTUAL PAYMENT
    # -------------------------
    gout_df["Projected Cash Masked"] = gout_df["Projected Cash From Actual"].where(
        gout_df["Daily Paid"] == 0
    )
    
    # -------------------------
    # PLOTTING
    # -------------------------
    fig = go.Figure()
    
    # Bars: Infusions
    fig.add_bar(
        x=gout_df.index,
        y=gout_df["Infusions"],
        name="Infusions",
        yaxis="y",
        marker=dict(opacity=0.4)
    )
    
    # Line: Actual cumulative cash
    fig.add_scatter(
        x=gout_df.index,
        y=gout_df["Cumulative Cash"],
        mode="lines",
        name="Actual Cash Collected",
        line=dict(color="blue", width=3),
        yaxis="y2"
    )
    
    # Line: Projected cumulative cash (only unpaid dates)
    fig.add_scatter(
        x=gout_df.index,
        y=gout_df["Projected Cash Masked"],
        mode="lines",
        name="Projected Cash (Unpaid Infusions)",
        line=dict(color="blue", dash="dash", width=3),
        yaxis="y2"
    )
    
    fig.update_layout(
        xaxis_title="Infusion Date",
    
        # Left axis: infusions
        yaxis=dict(
            title="Infusions",
            rangemode="tozero"
        ),
    
        # Right axis: cash
        yaxis2=dict(
            title="Cumulative Cash ($)",
            overlaying="y",
            side="right",
            tickformat="$,.0f",
            rangemode="tozero"
        ),
    
        legend=dict(
            orientation="h",
            y=-0.25
        ),
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    
    # =========================
    # GOUT – MONTHLY CASH COLLECTED
    # =========================
    st.subheader("Gout Program – Monthly Cash Collected")
    
    gout_monthly = (
        daily_gout
        .copy()
        .assign(
            Month=lambda x: x.index.to_period("M").astype(str)
        )
        .groupby("Month", as_index=False)["Cumulative Cash"]
        .max()
    )
    
    # Convert cumulative → monthly delta
    gout_monthly["Monthly Cash Collected"] = (
        gout_monthly["Cumulative Cash"]
        .diff()
        .fillna(gout_monthly["Cumulative Cash"])
    )
    
    fig = go.Figure()
    
    fig.add_bar(
        x=gout_monthly["Month"],
        y=gout_monthly["Monthly Cash Collected"],
        name="Gout Cash Collected",
    )
    
    fig.update_layout(
        xaxis_title="Month",
        yaxis_title="Cash Collected ($)",
        yaxis_tickformat="$,.0f",
    )
    
    st.plotly_chart(fig, use_container_width=True)


# =========================
# 340b CUMULATIVE REVENUE OVER TIME
# (STACKED BAR: ACTUAL + POTENTIAL)
# =========================
st.subheader("Cumulative 340b Revenue Over Time")

# Aggregate daily
daily = (
    df_filtered.groupby("Date", as_index=False)
      .agg({
          "Actual Revenue": "sum",
          "Potential Revenue (Included)": "sum"
      })
      .sort_values("Date")
)

# Cumulatives
daily["Cumulative Actual"] = daily["Actual Revenue"].cumsum()
daily["Cumulative Potential"] = daily["Potential Revenue (Included)"].cumsum()

fig = go.Figure()

# --- Stacked bars (daily) ---
fig.add_bar(
    x=daily["Date"],
    y=daily["Actual Revenue"],
    name="Actual Revenue (Paid)",
)

if include_potential:
    fig.add_bar(
        x=daily["Date"],
        y=daily["Potential Revenue (Included)"],
        name="Potential Revenue (Last 30 Days)",
        marker=dict(opacity=0.5)
    )

# --- Cumulative lines ---
fig.add_scatter(
    x=daily["Date"],
    y=daily["Cumulative Actual"],
    mode="lines",
    name="Cumulative Actual Revenue",
    line=dict(width=3),
    yaxis="y2"
)

if include_potential:
    fig.add_scatter(
        x=daily["Date"],
        y=daily["Cumulative Actual"] + daily["Cumulative Potential"],
        mode="lines",
        name="Cumulative Revenue + Potential",
        line=dict(dash="dot", width=3),
        yaxis="y2"
    )

fig.update_layout(
    barmode="stack",
    xaxis_title="Date",
    yaxis_title="Daily Revenue ($)",
    yaxis_tickformat="$,.0f",
    yaxis2=dict(
        title="Cumulative Revenue ($)",
        overlaying="y",
        side="right",
        tickformat="$,.0f"
    ),
    legend=dict(orientation="h", y=-0.25),
)

st.plotly_chart(fig, use_container_width=True)



# =========================
# TOP-N SLIDERS (DYNAMIC)
# =========================
st.sidebar.header("Top-N Controls")

top_n_bizdev = st.sidebar.slider(
    "Top Biz Dev",
    1, df["Biz Dev Name"].nunique(),
    df["Biz Dev Name"].nunique()
)

top_n_med = st.sidebar.slider(
    "Top Medications",
    1, df["Dispensed Drug"].nunique(),
    20
)

top_n_phys = st.sidebar.slider(
    "Top Physicians",
    1, df["Prescriber Full Name"].nunique(),
    20
)

# =========================
# 340B – MONTHLY CASH COLLECTED (ACTUAL)
# =========================
st.subheader("340B Program – Monthly Cash Collected (Actual)")

df_340b = df_filtered[df_filtered["Inventory_Type"] == "340B"].copy()

monthly_340b = (
    df_340b
    .groupby("Month", as_index=False)["Actual Revenue"]
    .sum()
    .sort_values("Month")
)

fig = go.Figure()

fig.add_bar(
    x=monthly_340b["Month"],
    y=monthly_340b["Actual Revenue"],
    name="340B Cash Collected",
)

fig.update_layout(
    xaxis_title="Month",
    yaxis_title="Cash Collected ($)",
    yaxis_tickformat="$,.0f",
)

st.plotly_chart(fig, use_container_width=True)

st.divider()
# =========================
# REVENUE BY Biz Dev 
# =========================
st.subheader("Revenue by Biz Dev")

by_rep = (
    df_filtered.groupby("Biz Dev Name", as_index=False)[
        ["Actual Revenue", "Potential Revenue (Included)"]
    ]
    .sum()
)

by_rep["Total"] = by_rep["Actual Revenue"] + by_rep["Potential Revenue (Included)"]
by_rep = by_rep.sort_values("Total", ascending=False).head(top_n_bizdev)

show_table_bizdev = st.checkbox("Show Biz Dev Revenue Table", value=False)

#Only for table display
by_rep_display = by_rep.copy()
for col in ["Actual Revenue", "Potential Revenue (Included)", "Total"]:
    if col in by_rep_display.columns:
        by_rep_display[col] = by_rep_display[col].map("${:,.0f}".format)

#Show Biz Dev table optinally
if show_table_bizdev:
    st.caption(date_range_label)

    st.dataframe(
        by_rep_display,
        use_container_width=True,
        height=300
    )

fig = go.Figure()

fig.add_bar(
    y=by_rep["Biz Dev Name"],
    x=by_rep["Actual Revenue"],
    orientation="h",
    name="Actual Revenue",
    text=by_rep["Actual Revenue"],
    texttemplate="$%{text:,.0f}",
    textposition="outside"
)

if include_potential:
    fig.add_bar(
        y=by_rep["Biz Dev Name"],
        x=by_rep["Potential Revenue (Included)"],
        orientation="h",
        name="Potential Additional Revenue",
        text=by_rep["Potential Revenue (Included)"],
        texttemplate="$%{text:,.0f}",
        textposition="outside",
        marker=dict(opacity=0.5)
    )


fig.update_layout(
    barmode="stack",
    xaxis_title="Revenue ($)",
    yaxis_title="Biz Dev Name",
    xaxis_tickformat="$,.0f",
    margin=dict(l=140, r=200, t=40, b=40),
    xaxis=dict(
        tickformat="$,.0f",
        automargin=True
        )
)


st.plotly_chart(fig, use_container_width=True)

# Add date range column for export
by_rep_export = by_rep.copy()
by_rep_export.insert(0, "Date Range", date_range_label)

st.download_button(
    "⬇️ Download Revenue by Biz Dev (PHI-Safe)",
    data=by_rep_export.to_csv(index=False).encode("utf-8"),
    file_name=f"revenue_by_biz_dev_{start_dt.date()}_to_{end_dt.date()}.csv",
    mime="text/csv"
)

st.divider()
# =========================
# REVENUE BY MEDICATION (FINAL)
# =========================
st.subheader("Revenue by Medication")
show_table_med = st.checkbox("Show Medication Revenue Table", value=False)
by_med = (
    df_filtered.groupby("Dispensed Drug", as_index=False)
      .agg({
          "Actual Revenue": "sum",
          "Potential Revenue (Included)": "sum"
      })
)
#Sort first, then filter
by_med["Total"] = by_med["Actual Revenue"] + by_med["Potential Revenue (Included)"]
by_med = by_med.sort_values("Total", ascending=False).head(top_n_med)
by_med_display = by_med.copy()
for col in ["Actual Revenue", "Potential Revenue (Included)", "Total"]:
    if col in by_med_display.columns:
        by_med_display[col] = by_med_display[col].map("${:,.0f}".format)


#OPTIONALLY SHOW TABLE REVENUE BY MEDICATION)
if show_table_med:
    st.caption(date_range_label)

    st.dataframe(
        by_med_display,
        use_container_width=True,
        height=300
    )
#PLOT REVENUE BY MEDICATION    
fig = go.Figure()

fig.add_bar(
    y=by_med["Dispensed Drug"],
    x=by_med["Actual Revenue"],
    orientation="h",
    name="Actual Revenue",
    text=by_med["Actual Revenue"],
    texttemplate="$%{text:,.0f}",
    textposition="outside"
)

if include_potential and "Potential Revenue (Included)" in by_med.columns:
    fig.add_bar(
        y=by_med["Dispensed Drug"],
        x=by_med["Potential Revenue (Included)"],
        orientation="h",
        name="Potential Additional Revenue",
        text=by_med["Potential Revenue (Included)"],
        texttemplate="$%{text:,.0f}",
        textposition="outside",
        marker=dict(opacity=0.45)
    )

fig.update_layout(
    barmode="stack",
    xaxis_title="Revenue ($)",
    yaxis_title="Medication",
    xaxis=dict(
        tickformat="$,.0f",
        automargin=True
    ),
    uniformtext_minsize=8,
    uniformtext_mode="show",
    height=max(400, 28 * len(by_med))

)

st.plotly_chart(fig, use_container_width=True)

by_med_export = by_med.copy()
by_med_export.insert(0, "Date Range", date_range_label)

st.download_button(
    "⬇️ Download Revenue by Medication (PHI-Safe)",
    data=by_med_export.to_csv(index=False).encode("utf-8"),
    file_name=f"revenue_by_medication_{start_dt.date()}_to_{end_dt.date()}.csv",
    mime="text/csv"
)



st.divider()
# =========================
# REVENUE BY PHYSICIAN (FINAL)
# =========================
st.subheader("Revenue by Physician")
show_table_phys = st.checkbox("Show Physician Revenue Table", value=False)

by_phys = (
    df_filtered.groupby("Prescriber Full Name", as_index=False)
      .agg({
          "Actual Revenue": "sum",
          "Potential Revenue (Included)": "sum"
      })
)
#Sort first, then filter
by_phys["Total"] = by_phys["Actual Revenue"] + by_phys["Potential Revenue (Included)"]
by_phys = by_phys.sort_values("Total", ascending=False).head(top_n_phys)
by_phys_display = by_phys.copy()

for col in ["Actual Revenue", "Potential Revenue (Included)", "Total"]:
    if col in by_phys_display.columns:
        by_phys_display[col] = by_phys_display[col].map("${:,.0f}".format)


#REV BY PHYSICIAN Table display
if show_table_phys:
    st.caption(date_range_label)

    st.dataframe(
        by_phys_display,
        use_container_width=True,
        height=300
    )


fig = go.Figure()

fig.add_bar(
    y=by_phys["Prescriber Full Name"],
    x=by_phys["Actual Revenue"],
    orientation="h",
    name="Actual Revenue",
    text=by_phys["Actual Revenue"],
    texttemplate="$%{text:,.0f}",
    textposition="outside"
)


if include_potential:
    fig.add_bar(
        y=by_phys["Prescriber Full Name"],
        x=by_phys["Potential Revenue (Included)"],
        orientation="h",
        name="Potential Additional Revenue",
        marker=dict(opacity=0.45)
    )

fig.update_layout(
    barmode="stack",
    xaxis_title="Revenue ($)",
    yaxis_title="Physician",
    uniformtext_minsize=8,
    uniformtext_mode="show",
    height=max(400, 28 * len(by_phys))    
)

st.plotly_chart(fig, use_container_width=True)

by_phys_export = by_phys.copy()
by_phys_export.insert(0, "Date Range", date_range_label)

st.download_button(
    "⬇️ Download Revenue by Physician (PHI-Safe)",
    data=by_phys_export.to_csv(index=False).encode("utf-8"),
    file_name=f"revenue_by_physician_{start_dt.date()}_to_{end_dt.date()}.csv",
    mime="text/csv"
)


# =========================
# PHI-SAFE EXPORT DATASET (AUTHORITATIVE)
# =========================
export_claims = make_phi_safe(df_filtered.copy())

st.divider()
# =========================
# RAW CLAIMS DATA (VIEW + DOWNLOAD)
# =========================
st.subheader("Claim-Level Detail (Filtered, PHI-Safe)")

st.caption(
    "All exports are automatically de-identified "
    "(patient names, contact details, MRNs removed)."
)

# On-screen table without PHI data
st.caption(
    "🔒 Patient identifiers are hidden on screen and removed from all downloads."
)

st.dataframe(
    phi_safe_df.sort_values("Date", ascending=False),
    use_container_width=True,
    height=450
)


# ---- CSV EXPORT (PHI-SAFE) ----
st.download_button(
    label="⬇️ Download Claims (PHI-Safe CSV)",
    data=export_claims.to_csv(index=False).encode("utf-8"),
    file_name="claims_phi_safe.csv",
    mime="text/csv"
)

# ---- EXCEL EXPORT (PHI-SAFE, CLOUD-SAFE) ----
from io import BytesIO

excel_buffer = BytesIO()
with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
    export_claims.to_excel(writer, index=False, sheet_name="Claims")

st.download_button(
    label="⬇️ Download Claims (PHI-Safe Excel)",
    data=excel_buffer.getvalue(),
    file_name="claims_phi_safe.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)



# =========================
# CONSOLIDATED EXPORT
# =========================
from io import BytesIO

output = BytesIO()
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    by_rep_export.to_excel(writer, sheet_name="By_Biz_Dev", index=False)
    by_med_export.to_excel(writer, sheet_name="By_Medication", index=False)
    by_phys_export.to_excel(writer, sheet_name="By_Physician", index=False)
    phi_safe_df.assign(**{"Date Range": date_range_label}).to_excel(
        writer, sheet_name="Claims", index=False
    )

st.download_button(
    "⬇️ Download Full Revenue Workbook (PHI-Safe)",
    data=output.getvalue(),
    file_name=f"revenue_summary_{start_dt.date()}_to_{end_dt.date()}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)