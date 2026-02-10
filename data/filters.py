def apply_user_scope(df, user):
    """Filter the doctors dataframe based on user role."""
    role = user["role"]

    if role == "admin":
        return df

    if role == "bizdev":
        bizdev_name = user.get("bizdev_name", "")
        return df[df["bizdev"].str.lower() == bizdev_name.lower()]

    if role == "viewer":
        doctor_names = [d.lower() for d in user.get("doctors", [])]
        if "doctor_name" in df.columns:
            return df[df["doctor_name"].str.lower().isin(doctor_names)]
        return df.iloc[0:0]

    if role == "investor":
        return (
            df.groupby("bizdev")
            .agg(doctors=("doctor_name", "nunique"))
            .reset_index()
        )

    return df.iloc[0:0]


def apply_claims_scope(df, user):
    """Filter the claims dataframe based on user role.

    Admins see all claims.  BizDev users see only claims from their doctors
    (matched via the 'Biz Dev Name' column).  Viewers see only claims from
    their assigned doctors (matched via 'Prescriber Full Name').
    """
    role = user["role"]

    if role == "admin":
        return df

    if role == "bizdev":
        bizdev_name = user.get("bizdev_name", "")
        return df[df["Biz Dev Name"].str.lower() == bizdev_name.lower()]

    if role == "viewer":
        doctor_names = [d.lower() for d in user.get("doctors", [])]
        return df[df["Prescriber Full Name"].str.lower().isin(doctor_names)]

    return df.iloc[0:0]
