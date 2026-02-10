def apply_user_scope(df, user):
    """Filter the doctors dataframe based on user role."""
    role = user["role"]

    if role == "admin":
        return df

    if role == "bizdev":
        bizdev_name = user.get("bizdev_name", "")
        return df[df["bizdev"].str.lower() == bizdev_name.lower()]

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
    (matched via the 'Biz Dev Name' column).
    """
    role = user["role"]

    if role == "admin":
        return df

    if role == "bizdev":
        bizdev_name = user.get("bizdev_name", "")
        return df[df["Biz Dev Name"].str.lower() == bizdev_name.lower()]

    return df.iloc[0:0]
