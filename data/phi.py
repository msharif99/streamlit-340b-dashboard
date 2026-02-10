import pandas as pd

PHI_COLUMNS = {
    "Patient Full Name",
    "Patient Contact #",
    "Patient Phone",
    "Patient Phone #",
    "Patient Email",
    "Patient Address",
    "MRN",
    "Medical Record Number",
}

def make_phi_safe(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in df.columns if c.strip() in PHI_COLUMNS]
    return df.drop(columns=cols, errors="ignore")

