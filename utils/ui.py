import streamlit as st

def safe_top_n_slider(
    label: str,
    count: int,
    default: int | None = None,
    sidebar: bool = True,
    help: str | None = None,
):
    """
    Safely render a Top-N slider.

    - If count <= 1 → returns 1 and shows a caption
    - Otherwise → renders a slider [1, count]

    Parameters
    ----------
    label : str
        Slider label
    count : int
        Number of unique items
    default : int | None
        Default slider value (defaults to count)
    sidebar : bool
        Render in sidebar if True
    help : str | None
        Optional help text

    Returns
    -------
    int
        Selected Top-N value
    """
    container = st.sidebar if sidebar else st

    if count <= 1:
        container.caption(f"{label}: only one available")
        return 1

    if default is None:
        default = count

    return container.slider(
        label,
        min_value=1,
        max_value=count,
        value=min(default, count),
        help=help,
    )

