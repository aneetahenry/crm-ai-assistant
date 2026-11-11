from typing import Optional, Tuple

import pandas as pd
import plotly.express as px


def choose_chart_type(df: pd.DataFrame, query: str, preferred: Optional[str] = None):
    if preferred:
        return preferred

    lower_query = query.lower()
    if any(token in lower_query for token in ["trend", "monthly", "month", "date", "over time", "sales trend"]):
        return "line"
    if any(token in lower_query for token in ["distribution", "status", "by status", "share", "proportion", "lead"]):
        return "pie"
    if any(token in lower_query for token in ["compare", "top", "highest", "city", "category", "product"]):
        return "bar"
    if any(token in lower_query for token in ["relationship", "vs", "versus", "scatter", "correlation"]):
        return "scatter"
    if len(df.columns) >= 2 and df.select_dtypes(include="number").shape[1] >= 1:
        return "bar"
    return "table"


def infer_axis_columns(df: pd.DataFrame, query: str) -> Tuple[str, str]:
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    object_cols = [c for c in df.columns if pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c])]
    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]

    low_query = query.lower()
    x_col = None
    y_col = None

    for candidate in ["city", "state", "category", "status", "source", "employee", "product", "month", "date", "name"]:
        if candidate in low_query:
            match = [col for col in df.columns if candidate in col.lower()]
            if match:
                x_col = match[0]
                break
    if x_col is None:
        if date_cols:
            x_col = date_cols[0]
        elif object_cols:
            x_col = object_cols[0]
        elif numeric_cols:
            x_col = numeric_cols[0]

    for candidate in ["amount", "revenue", "sales", "total", "quantity", "price", "count"]:
        if candidate in low_query:
            match = [col for col in numeric_cols if candidate in col.lower()]
            if match:
                y_col = match[0]
                break
    if y_col is None and numeric_cols:
        y_col = numeric_cols[0]

    if x_col == y_col and len(df.columns) > 1:
        for col in df.columns:
            if col != x_col:
                x_col = col
                break

    if numeric_cols:
        return x_col or df.columns[0], y_col or numeric_cols[0]
    return x_col or df.columns[0], y_col or df.columns[-1]


def auto_visualize(df: pd.DataFrame, user_query: str, preferred_chart: Optional[str] = None, x_col: Optional[str] = None, y_col: Optional[str] = None):
    if df is None or df.empty or len(df.columns) < 2:
        return None

    chart_type = choose_chart_type(df, user_query, preferred_chart)
    if chart_type == "table":
        return None

    x_axis, y_axis = infer_axis_columns(df, user_query)
    if x_col:
        x_axis = x_col
    if y_col:
        y_axis = y_col

    if chart_type == "line":
        if x_axis and y_axis:
            fig = px.line(df, x=x_axis, y=y_axis, markers=True, title=f"Trend: {user_query}")
            fig.update_layout(template="plotly_white", xaxis_tickangle=-45)
            return fig
    elif chart_type == "bar":
        if x_axis and y_axis:
            fig = px.bar(df, x=x_axis, y=y_axis, text_auto=True, title=f"Insights: {user_query}")
            fig.update_layout(template="plotly_white", xaxis_tickangle=-45)
            return fig
    elif chart_type == "pie":
        if x_axis and y_axis:
            fig = px.pie(df, names=x_axis, values=y_axis, title=f"Breakdown: {user_query}")
            return fig
    elif chart_type == "scatter":
        if x_axis and y_axis:
            fig = px.scatter(df, x=x_axis, y=y_axis, title=f"Relationship: {user_query}")
            return fig
    elif chart_type == "histogram":
        if y_axis:
            fig = px.histogram(df, x=y_axis, title=f"Distribution: {user_query}")
            return fig

    if x_axis and y_axis:
        fig = px.bar(df, x=x_axis, y=y_axis, title=f"Insights: {user_query}")
        fig.update_layout(template="plotly_white", xaxis_tickangle=-45)
        return fig

    return None
