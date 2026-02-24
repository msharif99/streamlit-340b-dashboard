import duckdb

CSV_PATH = "medicare_raw.csv"
PARQUET_PATH = "medicare.parquet"

con = duckdb.connect()

con.execute(f"""
    COPY (
        SELECT
            *,
            CASE
                WHEN Tot_Clms > 0 THEN Tot_Drug_Cst / Tot_Clms
                ELSE NULL
            END AS Cost_Per_Claim,
            CASE
                WHEN Tot_Benes > 0 THEN Tot_Drug_Cst / Tot_Benes
                ELSE NULL
            END AS Cost_Per_Beneficiary
        FROM read_csv_auto('{CSV_PATH}', IGNORE_ERRORS=TRUE)
    )
    TO '{PARQUET_PATH}'
    (FORMAT PARQUET)
""")

print("Parquet created")
