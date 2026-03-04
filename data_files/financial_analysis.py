"""
340B Financial Analysis Script
Calculates month-by-month breakdown of:
  1) Total Price Paid
  2) 340B Value (paid claims only)
  3) Spread: Total Price Paid - 340B Value
  4) WAC Value of unfilled scripts (Total Price Paid = 0)
  5) Rx Priority reasons for unfilled scripts (past 3 months, deduplicated)
"""

import pandas as pd
from pathlib import Path

DATA_FILE = Path(__file__).parent / "claims_with_pricing_v3.csv"


def load_and_prepare(path: str | Path = DATA_FILE) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Created On"] = pd.to_datetime(df["Created On"], format="%m-%d-%Y")
    df["Month"] = df["Created On"].dt.to_period("M")

    for col in ["Total Price Paid", "WAC Value", "340B Value", "WAC Price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(r"[\$,]", "", regex=True),
                errors="coerce",
            ).fillna(0)
    return df


def dedup_unfilled(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicate unfilled scripts: same patient + drug + month.
    Keeps the row with the highest WAC Value (most complete fill attempt)."""
    unpaid = df[df["Total Price Paid"] == 0].copy()
    unpaid = (
        unpaid.sort_values("WAC Value", ascending=False)
        .drop_duplicates(subset=["Patient Full Name", "Dispensed Drug", "Month"], keep="first")
    )
    paid = df[df["Total Price Paid"] > 0]
    return pd.concat([paid, unpaid], ignore_index=True)


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Build month-by-month financial summary."""
    months = sorted(df["Month"].unique())
    paid = df[df["Total Price Paid"] > 0]
    unpaid = df[df["Total Price Paid"] == 0]

    rows = []
    for m in months:
        tp = paid.loc[paid["Month"] == m, "Total Price Paid"].sum()
        b340 = paid.loc[paid["Month"] == m, "340B Value"].sum()
        spread = tp - b340
        wac = unpaid.loc[unpaid["Month"] == m, "WAC Value"].sum()
        rows.append({
            "Month": str(m),
            "Total Price Paid": tp,
            "340B Value": b340,
            "Spread": spread,
            "WAC (Unfilled)": wac,
        })

    summary = pd.DataFrame(rows)
    totals = summary[["Total Price Paid", "340B Value", "Spread", "WAC (Unfilled)"]].sum()
    totals["Month"] = "TOTAL"
    summary = pd.concat([summary, pd.DataFrame([totals])], ignore_index=True)
    return summary


def unfilled_by_reason(df: pd.DataFrame, months_back: int = 3) -> pd.DataFrame:
    """Rx Priority breakdown for unfilled scripts (past N months), deduplicated.
    Returns both script count AND WAC value per reason per month."""
    df_dedup = dedup_unfilled(df)
    unpaid = df_dedup[df_dedup["Total Price Paid"] == 0].copy()

    cutoff = df["Created On"].max() - pd.DateOffset(months=months_back)
    recent = unpaid[unpaid["Created On"] >= cutoff].copy()
    recent["Rx Priority"] = recent["Rx Priority"].fillna("Unknown")

    pivot_count = (
        recent.groupby(["Rx Priority", "Month"]).size()
        .unstack(fill_value=0)
    )
    pivot_count["Total Scripts"] = pivot_count.sum(axis=1)

    pivot_wac = (
        recent.groupby(["Rx Priority", "Month"])["WAC Value"].sum()
        .unstack(fill_value=0)
    )
    pivot_wac["Total WAC"] = pivot_wac.sum(axis=1)

    combined = pivot_count[["Total Scripts"]].join(pivot_wac[["Total WAC"]])

    # Add per-month columns
    for m in sorted(recent["Month"].unique()):
        combined[f"{m} Scripts"] = pivot_count.get(m, 0)
        combined[f"{m} WAC"] = pivot_wac.get(m, 0)

    combined = combined.sort_values("Total WAC", ascending=False)
    return combined


def print_report(df: pd.DataFrame) -> None:
    """Print full analysis to console."""
    summary = monthly_summary(df)

    print("=" * 80)
    print("MONTH-BY-MONTH FINANCIAL SUMMARY")
    print("=" * 80)
    print(f"{'Month':<10} {'Total Paid':>14} {'340B Value':>14} {'Spread':>14} {'WAC (Unfilled)':>14}")
    print("-" * 70)
    for _, row in summary.iterrows():
        print(
            f"{row['Month']:<10} "
            f"${row['Total Price Paid']:>12,.2f} "
            f"${row['340B Value']:>12,.2f} "
            f"${row['Spread']:>12,.2f} "
            f"${row['WAC (Unfilled)']:>12,.2f}"
        )

    print("\n\n" + "=" * 80)
    print("UNFILLED SCRIPTS BY RX PRIORITY (PAST 3 MONTHS — DEDUPLICATED)")
    print("  Dedup: same patient + same drug + same month = counted once")
    print("=" * 80)

    reason_df = unfilled_by_reason(df, months_back=3)

    # Summary header
    total_scripts = reason_df["Total Scripts"].sum()
    total_wac = reason_df["Total WAC"].sum()
    print(f"\n  Total deduplicated unfilled scripts: {total_scripts:,}")
    print(f"  Total WAC value at risk:             ${total_wac:,.0f}\n")

    print(f"  {'Rx Priority':<45} {'Scripts':>8} {'WAC Value':>14}")
    print("  " + "-" * 70)
    for reason, row in reason_df.iterrows():
        print(f"  {str(reason):<45} {int(row['Total Scripts']):>8} ${row['Total WAC']:>12,.0f}")
    print("  " + "-" * 70)
    print(f"  {'TOTAL':<45} {int(total_scripts):>8} ${total_wac:>12,.0f}")

    # Month-by-month detail for top reasons
    recent_months = sorted([c.replace(" Scripts", "") for c in reason_df.columns if c.endswith(" Scripts") and c != "Total Scripts"])
    print(f"\n  Month-by-month detail:")
    header = f"  {'Rx Priority':<40}"
    for m in recent_months:
        header += f"  {m:>18}"
    header += f"  {'Total':>18}"
    print(header)
    print("  " + "-" * (40 + 20 * (len(recent_months) + 1)))

    for reason, row in reason_df.iterrows():
        line = f"  {str(reason):<40}"
        for m in recent_months:
            s = int(row.get(f"{m} Scripts", 0))
            w = row.get(f"{m} WAC", 0)
            line += f"  {s:>3} (${w:>10,.0f})"
        line += f"  {int(row['Total Scripts']):>3} (${row['Total WAC']:>10,.0f})"
        print(line)


if __name__ == "__main__":
    df = load_and_prepare()
    print_report(df)
