"""Genie ROI - adoption, engagement, quality and value KPIs for Genie spaces and Genie Code.

Reads Databricks system tables through a SQL warehouse. See README.md.
"""

import os

import pandas as pd
import streamlit as st
from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

import queries as q

st.set_page_config(page_title="Genie ROI", page_icon="📈", layout="wide")

WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID")
cfg = Config()


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
# With user authorization enabled (README), queries run with the viewer's own permissions.
# Otherwise they run as the app's service principal.
USER_TOKEN = st.context.headers.get("X-Forwarded-Access-Token")
VIEWER = st.context.headers.get("X-Forwarded-Email", "") if USER_TOKEN else ""


@st.cache_resource
def sp_connection():
    return sql.connect(
        server_hostname=cfg.host,
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    )


def execute(query: str, params: dict, token: str | None) -> pd.DataFrame:
    if not token:
        with sp_connection().cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall_arrow().to_pandas()
    with sql.connect(
        server_hostname=cfg.host, http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}", access_token=token
    ) as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall_arrow().to_pandas()


# `viewer` keys the cache per user so viewers never see each other's results; `_token` is not hashed.
@st.cache_data(ttl=3600, show_spinner="Querying system tables...")
def run(query: str, days: int, ws: str, humans: int, viewer: str, _token: str | None) -> pd.DataFrame:
    params = {k: v for k, v in {"days": days, "ws": ws, "humans": humans}.items() if f":{k}" in query}
    return execute(query, params, _token)


def safe_run(query: str, days: int, ws: str) -> pd.DataFrame | None:
    """Run a query; show the error instead of crashing (missing grants, table not enabled...)."""
    try:
        return run(query, days, ws, humans, VIEWER, USER_TOKEN)
    except Exception as e:  # noqa: BLE001
        st.warning(f"Query failed - check system table grants (see README). Details: {e}")
        return None


@st.cache_data(ttl=3600)
def space_names(viewer: str, _token: str | None) -> dict[str, str]:
    """Genie space titles visible in this workspace. Falls back to ids."""
    try:
        w = WorkspaceClient(host=cfg.host, token=_token, auth_type="pat") if _token else WorkspaceClient()
        resp = w.genie.list_spaces()
        return {s.space_id: s.title for s in (resp.spaces or [])}
    except Exception:  # noqa: BLE001
        return {}


def first_row(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {}
    return {k: (0 if pd.isna(v) else v) for k, v in df.iloc[0].to_dict().items()}


def pct(num, den) -> str:
    return f"{100 * num / den:.0f}%" if den else "-"


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
if not WAREHOUSE_ID:
    st.error("DATABRICKS_WAREHOUSE_ID is not set. Add a SQL warehouse resource to the app (see README).")
    st.stop()

with st.sidebar:
    st.header("Filters")
    days = st.select_slider("Lookback window (days)", options=[7, 30, 60, 90, 180, 365], value=90)
    ws = st.text_input("Workspace id (empty = all workspaces)", "").strip()
    humans = int(st.checkbox("Human users only", True, help="Exclude service principals and automated API callers"))
    months = days / 30.4

    st.header("ROI assumptions")
    st.caption("Defaults are placeholders: replace them with your own figures or survey results.")
    currency = st.text_input("Currency", "USD")
    hourly_cost = st.number_input("Loaded cost per hour", 0.0, 1000.0, 75.0, 5.0)
    st.subheader("Genie Code")
    min_per_code = st.number_input(
        "Minutes saved per active user-day", 0.0, 480.0, 20.0, 5.0,
        help="Valued per day of use rather than per interaction: agent mode can log thousands of events a day.",
    )
    st.subheader("Genie spaces")
    min_per_question = st.number_input("Business-user minutes saved per answered question", 0.0, 240.0, 10.0, 1.0)
    deflection = st.slider("% of questions that would otherwise be an analyst request", 0, 100, 20)
    min_per_request = st.number_input("Analyst minutes per ad-hoc request", 0.0, 480.0, 45.0, 5.0)
    st.subheader("Costs")
    include_compute = st.checkbox("Include estimated Genie warehouse cost (list price, USD)", True)
    other_costs_month = st.number_input("Other monthly costs (licences, enablement...)", 0.0, 1e7, 0.0, 100.0)

st.title("📈 Genie ROI")
st.caption(
    f"Last {days} days · {'workspace ' + ws if ws else 'all workspaces in the account'} · "
    f"querying as {VIEWER or 'the app service principal'} · source: Databricks system tables, cached 1 h"
)

tab_overview, tab_spaces, tab_code, tab_method = st.tabs(
    ["Overview & ROI", "Genie spaces", "Genie Code", "Methodology"]
)

# Shared data
code = first_row(safe_run(q.CODE_KPIS, days, ws))
genie = first_row(safe_run(q.GENIE_KPIS, days, ws))
cost_df = safe_run(q.GENIE_COST_ESTIMATE, days, ws) if include_compute else None
compute_cost = float(cost_df["genie_cost_estimate_usd"].fillna(0).sum()) if cost_df is not None else 0.0

# ---------------------------------------------------------------------------
# Overview & ROI
# ---------------------------------------------------------------------------
with tab_overview:
    st.subheader("Adoption at a glance")
    c = st.columns(4)
    c[0].metric("Genie spaces - active users", f"{genie.get('active_users', 0):,}")
    c[1].metric("Genie spaces - questions asked", f"{genie.get('questions', 0):,}")
    c[2].metric("Genie Code - active users", f"{code.get('active_users', 0):,}")
    c[3].metric("Genie Code - interactions", f"{code.get('interactions', 0):,}")

    up, down = genie.get("thumbs_up", 0), genie.get("thumbs_down", 0)
    c = st.columns(4)
    c[0].metric("Active Genie spaces", f"{genie.get('active_spaces', 0):,}")
    c[1].metric("Positive feedback rate", pct(up, up + down), help="Thumbs up / (up + down) on Genie answers")
    c[2].metric(
        "Questions per Genie user",
        f"{genie['questions'] / genie['active_users']:.1f}" if genie.get("active_users") else "-",
    )
    c[3].metric(
        "Interactions per Genie Code user",
        f"{code['interactions'] / code['active_users']:.1f}" if code.get("active_users") else "-",
    )

    st.subheader("Estimated value")
    answered = max(genie.get("questions", 0) - down, 0)
    code_hours = code.get("active_user_days", 0) * min_per_code / 60
    user_hours = answered * min_per_question / 60
    analyst_hours = answered * deflection / 100 * min_per_request / 60
    total_hours = code_hours + user_hours + analyst_hours
    value = total_hours * hourly_cost
    cost = compute_cost + other_costs_month * months
    roi = (value - cost) / cost if cost else None

    c = st.columns(4)
    c[0].metric("Hours saved", f"{total_hours:,.0f}")
    c[1].metric(f"Value ({currency})", f"{value:,.0f}")
    c[2].metric(f"Cost ({currency})", f"{cost:,.0f}")
    c[3].metric("ROI", f"{roi:.1f}x" if roi is not None else "-", help="(value - cost) / cost")

    st.dataframe(
        pd.DataFrame(
            [
                ["Genie Code", f"{code.get('active_user_days', 0):,} active user-days × {min_per_code:g} min", code_hours],
                ["Genie spaces - business users", f"{answered:,} answered questions × {min_per_question:g} min", user_hours],
                ["Genie spaces - analyst deflection",
                 f"{answered:,} × {deflection}% × {min_per_request:g} min", analyst_hours],
            ],
            columns=["Source", "Calculation", "Hours saved"],
        ).round(1),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "Questions = successful message events. Answered questions = questions - thumbs down. Cost = estimated Genie share of warehouse "
        f"list cost ({compute_cost:,.0f} USD) + other costs × {months:.1f} months. Genie Code usage cost is not "
        "included. All value figures depend on the assumptions in the sidebar."
    )

    with st.expander("Survey-based estimate (recommended by Databricks alongside system tables)"):
        st.caption("Use the time-savings answer from your internal Genie Code survey (see Methodology).")
        c = st.columns(3)
        survey_pct = c[0].number_input("Average time saved (%)", 0.0, 100.0, 15.0, 1.0)
        dev_hours_week = c[1].number_input("Hours of coding per user per week", 0.0, 60.0, 20.0, 1.0)
        weeks = days / 7
        survey_hours = code.get("active_users", 0) * dev_hours_week * weeks * survey_pct / 100
        c[2].metric("Genie Code hours saved (survey)", f"{survey_hours:,.0f}",
                    help=f"active users × {dev_hours_week:g} h/week × {weeks:.0f} weeks × {survey_pct:g}%")
        st.write(f"Value: **{survey_hours * hourly_cost:,.0f} {currency}**")

# ---------------------------------------------------------------------------
# Genie spaces
# ---------------------------------------------------------------------------
with tab_spaces:
    st.subheader("Engagement")
    daily = safe_run(q.GENIE_DAILY, days, ws)
    if daily is not None and not daily.empty:
        c = st.columns(2)
        c[0].caption("Questions per day")
        c[0].bar_chart(daily, x="date", y="questions")
        c[1].caption("Active users per day")
        c[1].line_chart(daily, x="date", y="active_users")

    monthly = safe_run(q.GENIE_MONTHLY, days, ws)
    if monthly is not None and not monthly.empty:
        st.caption("Monthly active users: new vs returning (returning = also active the previous month)")
        st.bar_chart(monthly, x="month", y=["new_users", "returning_users"])

    st.subheader("Quality")
    c = st.columns(4)
    c[0].metric("Thumbs up", f"{up:,}")
    c[1].metric("Thumbs down", f"{down:,}")
    c[2].metric("Regeneration rate", pct(genie.get("regenerations", 0), genie.get("questions", 0)))
    failed = genie.get("failed_questions", 0)
    c[3].metric("Failed message attempts", pct(failed, failed + genie.get("questions", 0)),
                help="Message events with a non-200 status, often a few API clients retrying")

    st.subheader("By space")
    by_space = safe_run(q.GENIE_BY_SPACE, days, ws)
    if by_space is not None and not by_space.empty:
        names = space_names(VIEWER, USER_TOKEN)
        by_space.insert(2, "space_name", by_space["space_id"].map(names).fillna(""))
        rated = by_space["thumbs_up"] + by_space["thumbs_down"]
        by_space["positive_pct"] = (100 * by_space["thumbs_up"] / rated.where(rated > 0)).round(0)
        sql_stats = safe_run(q.GENIE_SQL_BY_SPACE, days, ws)
        if sql_stats is not None and not sql_stats.empty:
            by_space = by_space.merge(sql_stats, on="space_id", how="left")
        st.dataframe(by_space, hide_index=True, use_container_width=True)
        st.caption("Space names are only resolved for spaces in the app's workspace that the app can see.")

    st.subheader("Top users")
    top = safe_run(q.GENIE_TOP_USERS, days, ws)
    if top is not None:
        st.dataframe(top, hide_index=True, use_container_width=True)

    st.subheader("Curation effort (space authors)")
    cur = safe_run(q.GENIE_CURATION, days, ws)
    if cur is not None and not cur.empty:
        st.bar_chart(cur, x="month", y=["instruction_changes", "sample_or_benchmark_questions", "benchmark_runs"])

    if cost_df is not None and not cost_df.empty:
        st.subheader("Estimated compute cost per warehouse")
        st.dataframe(cost_df, hide_index=True, use_container_width=True)

    with st.expander("Debug: raw feedback rating values"):
        st.dataframe(safe_run(q.GENIE_RATING_VALUES, days, ws), hide_index=True)

# ---------------------------------------------------------------------------
# Genie Code
# ---------------------------------------------------------------------------
with tab_code:
    st.info(
        "Since 7 May 2026 this table only records user-submitted interactions (chat, agent mode, inline "
        "assistant). Earlier counts also include background requests and look inflated."
    )
    daily = safe_run(q.CODE_DAILY, days, ws)
    if daily is not None and not daily.empty:
        c = st.columns(2)
        c[0].caption("Interactions per day")
        c[0].bar_chart(daily, x="date", y="interactions")
        c[1].caption("Daily active users")
        c[1].line_chart(daily, x="date", y="active_users")

    monthly = safe_run(q.CODE_MONTHLY, days, ws)
    if monthly is not None and not monthly.empty:
        st.caption("Monthly active users: new vs returning")
        st.bar_chart(monthly, x="month", y=["new_users", "returning_users"])

    c = st.columns(2)
    with c[0]:
        st.subheader("By workspace")
        st.dataframe(safe_run(q.CODE_BY_WORKSPACE, days, ws), hide_index=True, use_container_width=True)
    with c[1]:
        st.subheader("Top users")
        st.dataframe(safe_run(q.CODE_TOP_USERS, days, ws), hide_index=True, use_container_width=True)

# ---------------------------------------------------------------------------
# Methodology
# ---------------------------------------------------------------------------
with tab_method:
    st.markdown(open(os.path.join(os.path.dirname(__file__), "METHODOLOGY.md"), encoding="utf-8").read())
