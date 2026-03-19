import streamlit as st
from pymongo import MongoClient
import pandas as pd
import altair as alt
import numpy as np
from module1 import download_and_sync

# --- Page Config ---
st.set_page_config(page_title="Stock Data Warehouse", layout="wide")
st.title("📈 Stock Market Analytics Dashboard")

# --- Initialize Session State ---
if "connected" not in st.session_state:
    st.session_state.connected = False

# --- Connection UI ---
if not st.session_state.connected:
    st.info("Please connect to the database to view stock analytics.")
    if st.button("🔌 Connect to Database"):
        with st.spinner("Syncing and fetching data..."):
            download_and_sync()
            st.session_state.connected = True
            st.rerun()  # Refresh to show the dashboard
else:
    # --- Database Connection ---
    def get_data():
        client = MongoClient("mongodb://localhost:27017/")
        db = client["stock_database"]
        collection = db["volatility_data"]
        data = list(collection.find())
        df = pd.DataFrame(data)

        if not df.empty:
            if "_id" in df.columns:
                df = df.drop(columns=["_id"])

            # 1. Convert Date
            df["date"] = pd.to_datetime(df["date"])

            # 2. Force Numeric Conversion
            numeric_cols = [
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
            "Previous Day Underlying Volatility (D)": 0.01,
            "Current Day Underlying Daily Volatility (E) = Sqrt(0.995*D*D + 0.005*C*C)": 0.00000001,
            "Underlying Annualised Volatility (F) = E*Sqrt(365)": 0.10,
        }

        # --- 2. Sidebar UI ---
        st.sidebar.header("📊 Dashboard Controls")
        if st.sidebar.button("🔄 Reconnect/Sync"):
            st.session_state.connected = False
            st.rerun()

        sorted_symbols = sorted(df["symbol"].astype(str).unique())
        selected_symbol = st.sidebar.selectbox("Select Symbol", options=sorted_symbols)
        selected_metric = st.sidebar.selectbox(
            "Select Metric", options=list(metrics_map.keys())
        )

        min_date, max_date = df["date"].min().date(), df["date"].max().date()
        date_range = st.sidebar.date_input("Date Range", value=(min_date, max_date))

        # --- 3. Data Processing ---
        mask = df["symbol"] == selected_symbol
        if isinstance(date_range, tuple) and len(date_range) == 2:
            mask &= (df["date"].dt.date >= date_range[0]) & (
                df["date"].dt.date <= date_range[1]
            )

        filtered_df = df[mask].sort_values("date").copy()

        # --- 4. Main UI Layout ---
        if not filtered_df.empty:
            st.subheader(f"📈 {selected_symbol} Performance")

            # Metrics Cards
            curr_val = filtered_df[selected_metric].iloc[-1]
            prev_val = (
                filtered_df[selected_metric].iloc[-2]
                if len(filtered_df) > 1
                else curr_val
            )
            delta = float(curr_val) - float(prev_val)

            m1, m2, m3 = st.columns(3)
            m1.metric(
                label=selected_metric, value=f"{curr_val:.4f}", delta=f"{delta:.4f}"
            )
            m2.metric(
                label="Period High", value=f"{filtered_df[selected_metric].max():.4f}"
            )
            m3.metric(
                label="Period Low", value=f"{filtered_df[selected_metric].min():.4f}"
            )

            # --- 5. Altair Chart ---
            interval = metrics_map[selected_metric]
            y_min, y_max = (
                filtered_df[selected_metric].min(),
                filtered_df[selected_metric].max(),
            )

            actual_range = y_max - y_min
            if interval == 0 or (actual_range / interval > 15):
                interval = actual_range / 4 if actual_range > 0 else 1

            tick_values = np.arange(
                (y_min // interval) * interval,
                (y_max // interval + 2) * interval,
                interval,
            ).tolist()

            nearest = alt.selection_point(
                nearest=True, on="mouseover", fields=["date"], empty=False, name="hover"
            )

            line = (
                alt.Chart(filtered_df)
                .mark_line(interpolate="monotone", color="#00d4ff", strokeWidth=3)
                .encode(
                    x=alt.X(
                        "date:T",
                        title="Timeline",
                        axis=alt.Axis(format="%b %d", labelAngle=-45, grid=False),
                    ),
                    y=alt.Y(
                        f"{selected_metric}:Q",
                        title=selected_metric,
                        scale=alt.Scale(
                            domain=[y_min * 0.99, y_max * 1.01], clamp=True
                        ),
                        axis=alt.Axis(
                            values=tick_values, grid=True, format=".2f", labelFlush=True
                        ),
                    ),
                )
            )

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

            selectors = (
                alt.Chart(filtered_df)
                .mark_point()
                .encode(x="date:T", opacity=alt.value(0))
                .add_params(nearest)
            )

            rules = (
                alt.Chart(filtered_df)
                .mark_rule(color="#666", strokeDash=[4, 4])
                .encode(x="date:T")
                .transform_filter(nearest)
            )

            points = line.mark_point(color="#00d4ff", size=80, filled=True).encode(
                opacity=alt.condition(nearest, alt.value(1), alt.value(0))
            )

            final_chart = (
                alt.layer(area, line, selectors, rules, points)
                .encode(
                    tooltip=[
                        alt.Tooltip("date:T", title="Date"),
                        alt.Tooltip(
                            f"{selected_metric}:Q", title="Value", format=".4f"
                        ),
                    ]
                )
                .properties(height=500)
                .interactive()
            )

            st.altair_chart(final_chart, use_container_width=True)

            with st.expander("📂 View Full Numerical Data"):
                st.dataframe(
                    filtered_df.select_dtypes(include=["number", "datetime"]),
                    use_container_width=True,
                )
        else:
            st.warning("No data found for the selected criteria.")
    else:
        st.error("No data found in MongoDB. Please run the sync script first.")
