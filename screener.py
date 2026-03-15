import streamlit as st
from pymongo import MongoClient
import pandas as pd
import altair as alt
import numpy as np
from module1 import download_and_sync

download_and_sync()
# --- Page Config ---
st.set_page_config(page_title="Stock Data Warehouse", layout="wide")
st.title("📈 Stock Market Analytics Dashboard")


# --- Database Connection ---
@st.cache_resource
def init_connection():
    # Replace with your actual MONGO_URI
    return MongoClient(st.secrets["mongo"]["uri"])


client = init_connection()


def get_data():
    db = client["my_database"]
    collection = db["latest_data"]
    data = list(collection.find())
    df = pd.DataFrame(data)

    if not df.empty:
        if "_id" in df.columns:
            df = df.drop(columns=["_id"])

        # 1. Convert Date
        df["Date"] = pd.to_datetime(df["Date"])

        # 2. Force Numeric Conversion (Crucial for plotting)
        numeric_cols = [
            "Underlying Close Price (A)",
            "Underlying Previous Day Close Price (B)",
            "Underlying Log Returns (C) = LN(A/B)",
            "Previous Day Underlying Volatility (D)",
            "Current Day Underlying Daily Volatility (E) = Sqrt(0.995*D*D + 0.005*C*C)",
            "Underlying Annualised Volatility (F) = E*Sqrt(365)",
        ]

        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


df = get_data()

if not df.empty:
    # --- 1. Metrics Mapping ---
    metrics_map = {
        "Underlying Close Price (A)": 50,
        "Underlying Previous Day Close Price (B)": 50,
        "Underlying Log Returns (C) = LN(A/B)": 0.02,
        "Previous Day Underlying Volatility (D)": 0.01,
        "Current Day Underlying Daily Volatility (E) = Sqrt(0.995*D*D + 0.005*C*C)": 0.01,
        "Underlying Annualised Volatility (F) = E*Sqrt(365)": 0.10,
    }

    # --- 2. Sidebar UI ---
    st.sidebar.header("📊 Dashboard Controls")
    selected_symbol = st.sidebar.selectbox(
        "Select Symbol", options=sorted(df["Symbol"].unique())
    )
    selected_metric = st.sidebar.selectbox(
        "Select Metric", options=list(metrics_map.keys())
    )

    min_date, max_date = df["Date"].min().date(), df["Date"].max().date()
    date_range = st.sidebar.date_input("Date Range", value=(min_date, max_date))

    # --- 3. Data Processing ---
    mask = df["Symbol"] == selected_symbol
    if isinstance(date_range, tuple) and len(date_range) == 2:
        mask &= (df["Date"].dt.date >= date_range[0]) & (
            df["Date"].dt.date <= date_range[1]
        )

    filtered_df = df[mask].sort_values("Date").copy()

    # --- 4. Main UI Layout ---
    if not filtered_df.empty:
        st.subheader(f"📈 {selected_symbol} Performance")

        # Metrics Cards
        curr_val = filtered_df[selected_metric].iloc[-1]
        prev_val = (
            filtered_df[selected_metric].iloc[-2] if len(filtered_df) > 1 else curr_val
        )
        delta = float(curr_val) - float(prev_val)

        m1, m2, m3 = st.columns(3)
        m1.metric(label=selected_metric, value=f"{curr_val:.2f}", delta=f"{delta:.4f}")
        m2.metric(
            label="Period High", value=f"{filtered_df[selected_metric].max():.2f}"
        )
        m3.metric(label="Period Low", value=f"{filtered_df[selected_metric].min():.2f}")

        # --- 5. Altair Chart with Selection Fix ---
        interval = metrics_map[selected_metric]
        y_min, y_max = (
            filtered_df[selected_metric].min(),
            filtered_df[selected_metric].max(),
        )

        # Dynamic Ticks calculation
        actual_range = y_max - y_min
        if interval == 0 or (actual_range / interval > 15):
            interval = actual_range / 8 if actual_range > 0 else 1

        tick_values = np.arange(
            (y_min // interval) * interval, (y_max // interval + 2) * interval, interval
        ).tolist()

        # Selection for Crosshair (Fix: Remove 'filter' parameter)
        nearest = alt.selection_point(
            nearest=True, on="mouseover", fields=["Date"], empty=False, name="hover"
        )

        # Base Line
        line = (
            alt.Chart(filtered_df)
            .mark_line(interpolate="monotone", color="#00d4ff", strokeWidth=3)
            .encode(
                x=alt.X(
                    "Date:T",
                    title="Timeline",
                    axis=alt.Axis(format="%b %d", labelAngle=-45, grid=False),
                ),
                y=alt.Y(
                    f"{selected_metric}:Q",
                    title=selected_metric,
                    scale=alt.Scale(domain=[y_min * 0.99, y_max * 1.01], clamp=True),
                    axis=alt.Axis(
                        values=tick_values, grid=True, format=".2f", labelFlush=True
                    ),
                ),
            )
        )

        # Glow Area
        area = line.mark_area(
            opacity=0.15,
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="#00d4ff", offset=0),
                    alt.GradientStop(color="transparent", offset=1),
                ],
                x1=1,
                x2=1,
                y1=1,
                y2=0,
            ),
        )

        # Interactive Layer components
        selectors = (
            alt.Chart(filtered_df)
            .mark_point()
            .encode(x="Date:T", opacity=alt.value(0))
            .add_params(nearest)
        )

        rules = (
            alt.Chart(filtered_df)
            .mark_rule(color="#666", strokeDash=[4, 4])
            .encode(x="Date:T")
            .transform_filter(nearest)
        )

        points = line.mark_point(color="#00d4ff", size=80, filled=True).encode(
            opacity=alt.condition(nearest, alt.value(1), alt.value(0))
        )

        # Combine Layers
        final_chart = (
            alt.layer(area, line, selectors, rules, points)
            .encode(
                tooltip=[
                    alt.Tooltip("Date:T", title="Date"),
                    alt.Tooltip(f"{selected_metric}:Q", title="Value", format=".4f"),
                ]
            )
            .properties(
                height=500, padding={"left": 40, "top": 10, "right": 10, "bottom": 10}
            )
            .interactive()
        )

        st.altair_chart(final_chart, use_container_width=True)

        # --- 6. Numerical Data Expander ---
        with st.expander("📂 View Full Numerical Data"):
            st.dataframe(
                filtered_df.select_dtypes(include=["number", "datetime"]),
                use_container_width=True,
            )
    else:
        st.warning("No data found for the selected criteria.")
else:
    st.error("No data found in MongoDB. Please run the sync script first.")
