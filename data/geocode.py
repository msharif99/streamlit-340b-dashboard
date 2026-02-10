import pandas as pd
import pgeocode
import streamlit as st

# Known facility coordinates (doctors sheet only has facility names)
FACILITY_COORDS = {
    "carepoint": {"lat": 40.6664, "lon": -74.1192, "label": "Carepoint (Bayonne, NJ)"},
    "insight":   {"lat": 40.7357, "lon": -74.0298, "label": "Insight (Jersey City, NJ)"},
}

@st.cache_data
def geocode_zips(zip_series: pd.Series) -> pd.DataFrame:
    """Convert a Series of zip codes to lat/lon using pgeocode (offline)."""
    nomi = pgeocode.Nominatim("us")
    zips_5 = zip_series.dropna().astype(str).str[:5]
    unique_zips = zips_5.unique().tolist()
    geo = nomi.query_postal_code(unique_zips)
    lookup = dict(zip(geo["postal_code"], zip(geo["latitude"], geo["longitude"])))

    df = pd.DataFrame({"zip5": zips_5})
    df["lat"] = df["zip5"].map(lambda z: lookup.get(z, (None, None))[0])
    df["lon"] = df["zip5"].map(lambda z: lookup.get(z, (None, None))[1])
    return df


def get_facility_points() -> pd.DataFrame:
    """Return a DataFrame of known doctor facility locations."""
    rows = []
    for key, info in FACILITY_COORDS.items():
        rows.append({"facility": info["label"], "lat": info["lat"], "lon": info["lon"]})
    return pd.DataFrame(rows)
