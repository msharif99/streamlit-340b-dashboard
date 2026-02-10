import plotly.express as px

def revenue_by_marketer(df):
    return px.bar(
        df,
        x=["Actual Revenue", "Potential Revenue (Included)"],
        y="Marketer Name",
        orientation="h",
        barmode="stack",
        title="Revenue by BizDev",
    )


