import json
import urllib.request
import pandas as pd
import pgeocode
import streamlit as st
from pathlib import Path

CACHE_FILE = Path(__file__).resolve().parent.parent / "data_files" / "npi_cache.json"


def _fetch_npi(npi: str) -> dict | None:
    """Query the CMS NPI Registry API for a single NPI."""
    url = f"https://npiregistry.cms.hhs.gov/api/?number={npi}&version=2.1"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        if data.get("result_count", 0) > 0:
            r = data["results"][0]
            addr = r["addresses"][0]
            basic = r.get("basic", {})
            name = basic.get("name") or f"{basic.get('last_name', '')}, {basic.get('first_name', '')}"
            return {
                "npi": npi,
                "name": name.strip(", "),
                "address": addr.get("address_1", ""),
                "city": addr.get("city", ""),
                "state": addr.get("state", ""),
                "zip": str(addr.get("postal_code", ""))[:5],
            }
    except Exception:
        pass
    return None


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def _save_cache(cache: dict):
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


@st.cache_data(ttl=86400, show_spinner="Looking up doctor locations via NPI Registry...")
def lookup_doctor_locations(npi_series: pd.Series) -> pd.DataFrame:
    """Look up practice addresses for a list of NPIs, with local JSON cache."""
    cache = _load_cache()

    npis = npi_series.dropna().astype(float).astype(int).astype(str).unique().tolist()
    results = []
    new_lookups = 0

    for npi in npis:
        if npi in cache:
            results.append(cache[npi])
        else:
            info = _fetch_npi(npi)
            if info:
                cache[npi] = info
                results.append(info)
                new_lookups += 1

    if new_lookups > 0:
        _save_cache(cache)

    if not results:
        return pd.DataFrame(columns=["npi", "name", "city", "state", "zip", "lat", "lon"])

    df = pd.DataFrame(results)

    # Geocode zip codes
    nomi = pgeocode.Nominatim("us")
    unique_zips = df["zip"].unique().tolist()
    geo = nomi.query_postal_code(unique_zips)
    zip_to_coords = dict(zip(geo["postal_code"], zip(geo["latitude"], geo["longitude"])))

    df["lat"] = df["zip"].map(lambda z: zip_to_coords.get(z, (None, None))[0])
    df["lon"] = df["zip"].map(lambda z: zip_to_coords.get(z, (None, None))[1])

    return df.dropna(subset=["lat", "lon"])
