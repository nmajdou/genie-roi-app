"""Genie ROI - adoption, engagement, quality and value KPIs for Genie spaces and Genie Code.

Reads four daily datasets (see queries.py) through a SQL warehouse, either from tables materialized by the
refresh job (fast) or live from the system tables, and computes every KPI from them. See README.md.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st
from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

import queries as q

st.set_page_config(page_title="Genie ROI", page_icon="📈", layout="wide")

WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID")
SCHEMA = os.getenv("GENIE_ROI_SCHEMA", "").strip()  # catalog.schema written by the refresh job; '' = live mode
cfg = Config()
print(f"Genie ROI starting - data source: {SCHEMA or 'live system tables'}", flush=True)

# With user authorization enabled (README), queries run with the viewer's own permissions.
# Otherwise they run as the app's service principal.
USER_TOKEN = st.context.headers.get("X-Forwarded-Access-Token")
VIEWER = st.context.headers.get("X-Forwarded-Email", "") if USER_TOKEN else ""


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
def execute(query: str, params: dict, token: str | None) -> pd.DataFrame:
    auth = {"access_token": token} if token else {"credentials_provider": lambda: cfg.authenticate}
    with sql.connect(
        server_hostname=cfg.host, http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}", **auth
    ) as conn, conn.cursor() as cur:
        cur.execute(query, {k: v for k, v in params.items() if f":{k}" in query})
        return cur.fetchall_arrow().to_pandas()


# `viewer` keys the cache per user so viewers never see each other's results; `_token` is not hashed.
@st.cache_data(ttl=3600, show_spinner=False)
def load_all(days: int, ws: str, humans: int, viewer: str, _token: str | None) -> dict:
    """Load the four datasets in parallel. Values are DataFrames, or error strings."""
    params = {"days": days, "ws": ws, "humans": humans}

    def load(name: str):
        try:
            df = execute(q.read_sql(name, SCHEMA) if SCHEMA else q.live_sql(name), params, _token)
            if "d" in df:
                df["d"] = pd.to_datetime(df["d"])
            for col in df.columns:  # DECIMAL sums arrive as Python Decimals
                first = df[col].dropna().head(1)
                if not first.empty and type(first.iloc[0]).__name__ == "Decimal":
                    df[col] = df[col].astype(float)
            return df
        except Exception as e:  # noqa: BLE001
            return str(e)

    with ThreadPoolExecutor(len(q.DATASETS)) as pool:
        return dict(zip(q.DATASETS, pool.map(load, q.DATASETS)))


@st.cache_data(ttl=3600)
def current_workspace_id() -> str:
    try:
        return str(WorkspaceClient().get_workspace_id())
    except Exception:  # noqa: BLE001
        return ""


@st.cache_data(ttl=3600)
def space_names(viewer: str, _token: str | None) -> dict[str, str]:
    """Genie space titles visible in this workspace. Falls back to ids."""
    try:
        w = WorkspaceClient(host=cfg.host, token=_token, auth_type="pat") if _token else WorkspaceClient()
        resp = w.genie.list_spaces()
        return {s.space_id: s.title for s in (resp.spaces or [])}
    except Exception:  # noqa: BLE001
        return {}


def pct(num, den) -> str:
    return f"{100 * num / den:.0f}%" if den else "-"


def monthly_users(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly active users split into new (first month seen) and returning (also active the month before)."""
    m = df.assign(month=df["d"].dt.to_period("M"))[["month", "user_email"]].drop_duplicates()
    first = m.groupby("user_email")["month"].transform("min")
    prev = set(zip(m["user_email"], m["month"] + 1))
    m["new_users"] = first == m["month"]
    m["returning_users"] = [(u, mo) in prev for u, mo in zip(m["user_email"], m["month"])]
    out = m.groupby("month")[["new_users", "returning_users"]].sum().reset_index()
    out["month"] = out["month"].dt.to_timestamp()
    return out


def show(df: pd.DataFrame | None):
    if df is not None and not df.empty:
        st.dataframe(df, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
if not WAREHOUSE_ID:
    st.error("DATABRICKS_WAREHOUSE_ID is not set. Add a SQL warehouse resource to the app (see README).")
    st.stop()

with st.sidebar:
    st.header("Filters")
    days = st.select_slider("Lookback window (days)", options=[7, 30, 60, 90, 180, 365], value=30)
    # Live mode scans the audit log on every load: default to this workspace to keep it fast.
    ws = st.text_input("Workspace id (empty = all workspaces)", "" if SCHEMA else current_workspace_id()).strip()
    humans = int(st.checkbox("Human users only", True, help="Exclude service principals and automated API callers"))
    if st.button("Refresh data"):
        load_all.clear()
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
    f"querying as {VIEWER or 'the app service principal'} · "
    + (f"source: `{SCHEMA}` (refreshed daily)" if SCHEMA else "source: system tables, live (cached 1 h)")
)

with st.spinner("Loading data..." if SCHEMA else "Querying system tables (live mode can take a minute)..."):
    data = load_all(days, ws, humans, VIEWER, USER_TOKEN)

frames = {}
for name, value in data.items():
    if isinstance(value, str):
        st.warning(f"Could not load `{name}` - check grants (see README). Details: {value[:500]}")
        frames[name] = None
    else:
        frames[name] = value
G, C, S, W = (frames[n] for n in q.DATASETS)

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
genie, code = {}, {}
if G is not None:
    asked = G[G["questions"] > 0]
    genie = G.drop(columns=["d", "workspace_id", "space_id", "user_email", "last_event"]).sum().to_dict()
    genie["active_users"] = asked["user_email"].nunique()
    genie["active_spaces"] = asked["space_id"].nunique()
if C is not None:
    code = {
        "interactions": int(C["interactions"].sum()),
        "active_users": C["user_email"].nunique(),
        "active_user_days": len(C[["user_email", "d"]].drop_duplicates()),
    }

cost_by_wh = None
if W is not None and not W.empty:
    cost_by_wh = W.groupby("warehouse_id")[["genie_ms", "all_ms", "list_cost_usd"]].sum().reset_index()
    cost_by_wh["genie_share_pct"] = (100 * cost_by_wh["genie_ms"] / cost_by_wh["all_ms"]).round(1)
    cost_by_wh["genie_cost_estimate_usd"] = (cost_by_wh["list_cost_usd"] * cost_by_wh["genie_ms"] / cost_by_wh["all_ms"]).round(2)
    cost_by_wh = cost_by_wh.drop(columns=["genie_ms", "all_ms"]).sort_values("genie_cost_estimate_usd", ascending=False)
compute_cost = float(cost_by_wh["genie_cost_estimate_usd"].sum()) if include_compute and cost_by_wh is not None else 0.0

up, down = int(genie.get("thumbs_up", 0)), int(genie.get("thumbs_down", 0))

tab_overview, tab_spaces, tab_code, tab_method = st.tabs(
    ["Overview & ROI", "Genie spaces", "Genie Code", "Methodology"]
)

# ---------------------------------------------------------------------------
# Overview & ROI
# ---------------------------------------------------------------------------
with tab_overview:
    st.subheader("Adoption at a glance")
    c = st.columns(4)
    c[0].metric("Genie spaces - active users", f"{genie.get('active_users', 0):,}")
    c[1].metric("Genie spaces - questions asked", f"{int(genie.get('questions', 0)):,}")
    c[2].metric("Genie Code - active users", f"{code.get('active_users', 0):,}")
    c[3].metric("Genie Code - interactions", f"{code.get('interactions', 0):,}")

    c = st.columns(4)
    c[0].metric("Active Genie spaces", f"{genie.get('active_spaces', 0):,}")
    c[1].metric("Positive feedback rate", pct(up, up + down), help="Thumbs up / (up + down) on Genie answers")
    c[2].metric(
        "Questions per Genie user",
        f"{genie['questions'] / genie['active_users']:.1f}" if genie.get("active_users") else "-",
    )
    c[3].metric(
        "Active days per Genie Code user",
        f"{code['active_user_days'] / code['active_users']:.1f}" if code.get("active_users") else "-",
    )

    st.subheader("Estimated value")
    answered = max(int(genie.get("questions", 0)) - down, 0)
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

    show(
        pd.DataFrame(
            [
                ["Genie Code", f"{code.get('active_user_days', 0):,} active user-days × {min_per_code:g} min", code_hours],
                ["Genie spaces - business users", f"{answered:,} answered questions × {min_per_question:g} min", user_hours],
                ["Genie spaces - analyst deflection",
                 f"{answered:,} × {deflection}% × {min_per_request:g} min", analyst_hours],
            ],
            columns=["Source", "Calculation", "Hours saved"],
        ).round(1)
    )
    st.caption(
        "Questions = successful message events. Answered questions = questions - thumbs down. Cost = estimated "
        f"Genie share of warehouse list cost ({compute_cost:,.0f} USD) + other costs × {months:.1f} months. "
        "Genie Code usage cost is not included. All value figures depend on the assumptions in the sidebar."
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
    if G is not None and not G.empty:
        asked = G[G["questions"] > 0]
        st.subheader("Engagement")
        daily = G.groupby("d")["questions"].sum().to_frame().join(asked.groupby("d")["user_email"].nunique().rename("active_users")).fillna(0).reset_index()
        c = st.columns(2)
        c[0].caption("Questions per day")
        c[0].bar_chart(daily, x="d", y="questions")
        c[1].caption("Active users per day")
        c[1].line_chart(daily, x="d", y="active_users")
        st.caption("Monthly active users: new vs returning (returning = also active the previous month)")
        st.bar_chart(monthly_users(asked), x="month", y=["new_users", "returning_users"])

        st.subheader("Quality")
        failed = int(genie.get("failed_questions", 0))
        c = st.columns(4)
        c[0].metric("Thumbs up", f"{up:,}")
        c[1].metric("Thumbs down", f"{down:,}")
        c[2].metric("Regeneration rate", pct(genie.get("regenerations", 0), genie.get("questions", 0)))
        c[3].metric("Failed message attempts", pct(failed, failed + genie.get("questions", 0)),
                    help="Message events with a non-200 status, often a few API clients retrying")

        st.subheader("By space")
        sums = ["questions", "conversations", "thumbs_up", "thumbs_down",
                "instruction_changes", "sample_or_benchmark_questions", "benchmark_runs"]
        by_space = G.dropna(subset=["space_id"]).groupby(["workspace_id", "space_id"]).agg(
            **{k: (k, "sum") for k in sums}, last_event=("last_event", "max"))
        by_space["users"] = asked.groupby(["workspace_id", "space_id"])["user_email"].nunique()
        by_space = by_space[by_space["questions"] > 0].reset_index()
        rated = by_space["thumbs_up"] + by_space["thumbs_down"]
        by_space["positive_pct"] = (100 * by_space["thumbs_up"] / rated.where(rated > 0)).round(0)
        by_space.insert(2, "space_name", by_space["space_id"].map(space_names(VIEWER, USER_TOKEN)).fillna(""))
        if S is not None and not S.empty:
            s = S.groupby("space_id")[["queries", "finished", "slow_queries", "total_ms", "read_bytes"]].sum()
            s["sql_success_pct"] = (100 * s["finished"] / s["queries"]).round(1)
            s["avg_sql_seconds"] = (s["total_ms"] / s["queries"] / 1000).round(1)
            s["slow_sql_pct"] = (100 * s["slow_queries"] / s["queries"]).round(1)
            s["gb_read"] = (s["read_bytes"] / 1024**3).round(2)
            s = s.rename(columns={"queries": "sql_queries"})[["sql_queries", "sql_success_pct", "avg_sql_seconds", "slow_sql_pct", "gb_read"]]
            by_space = by_space.merge(s, left_on="space_id", right_index=True, how="left")
        show(by_space.sort_values("questions", ascending=False))
        st.caption("Space names are only resolved for spaces in this workspace that you can see. "
                   "Slow SQL = longer than 10 seconds.")

        st.subheader("Top users")
        show(asked.groupby("user_email").agg(questions=("questions", "sum"), spaces=("space_id", "nunique"),
                                             active_days=("d", "nunique"), last_question=("last_event", "max"))
             .sort_values("questions", ascending=False).head(50).reset_index())

        st.subheader("Curation effort (space authors)")
        cur = G.assign(month=G["d"].dt.to_period("M").dt.to_timestamp()).groupby("month")[
            ["instruction_changes", "sample_or_benchmark_questions", "benchmark_runs"]].sum().reset_index()
        st.bar_chart(cur, x="month", y=["instruction_changes", "sample_or_benchmark_questions", "benchmark_runs"])

    if cost_by_wh is not None:
        st.subheader("Estimated compute cost per warehouse")
        show(cost_by_wh)

# ---------------------------------------------------------------------------
# Genie Code
# ---------------------------------------------------------------------------
with tab_code:
    st.info(
        "Since 7 May 2026 this table only records user-submitted interactions (chat, agent mode, inline "
        "assistant). Earlier counts also include background requests and look inflated."
    )
    if C is not None and not C.empty:
        daily = C.groupby("d").agg(interactions=("interactions", "sum"), active_users=("user_email", "nunique")).reset_index()
        c = st.columns(2)
        c[0].caption("Interactions per day")
        c[0].bar_chart(daily, x="d", y="interactions")
        c[1].caption("Daily active users")
        c[1].line_chart(daily, x="d", y="active_users")
        st.caption("Monthly active users: new vs returning")
        st.bar_chart(monthly_users(C), x="month", y=["new_users", "returning_users"])

        c = st.columns(2)
        with c[0]:
            st.subheader("By workspace")
            show(C.groupby("workspace_id").agg(interactions=("interactions", "sum"), active_users=("user_email", "nunique"))
                 .sort_values("interactions", ascending=False).reset_index())
        with c[1]:
            st.subheader("Top users")
            show(C.groupby("user_email").agg(interactions=("interactions", "sum"), active_days=("d", "nunique"),
                                             last_used=("last_event", "max"))
                 .sort_values("interactions", ascending=False).head(50).reset_index())

# ---------------------------------------------------------------------------
# Methodology
# ---------------------------------------------------------------------------
with tab_method:
    st.markdown(open(os.path.join(os.path.dirname(__file__), "METHODOLOGY.md"), encoding="utf-8").read())
