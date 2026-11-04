"""Genie survey - collects time-saved answers for Genie Code and Genie Agents into a Delta table.

Responses are written by the app's service principal, so respondents need no table permissions. They are
anonymous: no email or user id is stored. The Genie ROI app reads the table (GENIE_ROI_SURVEY_TABLE) and uses
the averages as its default assumptions. See README.md.
"""

import os
import re
import uuid
from datetime import datetime, timezone

import streamlit as st
from databricks import sql
from databricks.sdk.core import Config

st.set_page_config(page_title="Genie survey", page_icon="📝", layout="centered")

WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID")
TABLE = os.getenv("GENIE_ROI_SURVEY_TABLE", "").strip()
cfg = Config()

# Answer buckets and the midpoint stored for each, in the unit the Genie ROI app uses.
CODING_HOURS = {"Less than 5 h": 2.5, "5-10 h": 7.5, "10-20 h": 15, "20-30 h": 25, "More than 30 h": 32}
TIME_SAVED = {"0-10%": 5, "10-30%": 20, "30-50%": 40, "50-70%": 60, "More than 70%": 75}
MIN_BEFORE = {"Less than 5 min": 2.5, "5-15 min": 10, "15-30 min": 22.5, "30-60 min": 45, "More than 1 h": 75}
MIN_WITH = {"Less than 2 min": 1, "2-5 min": 3.5, "5-15 min": 10, "More than 15 min": 20}
ANALYST_MIN = {"Less than 15 min": 7.5, "15-30 min": 22.5, "30-60 min": 45, "1-2 h": 90, "More than 2 h": 150}
ASKED_ANALYST = "Asked an analyst or the data team"
SCALE = [1, 2, 3, 4, 5]

COLUMNS = [
    "response_id", "submitted_at", "survey", "role", "frequency", "where_used", "use_cases",
    "coding_hours", "time_saved_pct", "productivity", "satisfaction",
    "before_methods", "asked_analyst", "minutes_before", "minutes_with_genie", "minutes_saved",
    "analyst_minutes", "trust", "comments",
]
DDL = """CREATE TABLE IF NOT EXISTS {table} (
  response_id STRING, submitted_at TIMESTAMP, survey STRING COMMENT 'genie_code or genie_agents',
  role STRING, frequency STRING, where_used STRING, use_cases STRING,
  coding_hours DOUBLE COMMENT 'hours of coding per week (bucket midpoint)',
  time_saved_pct DOUBLE COMMENT 'share of coding time saved by Genie Code (bucket midpoint)',
  productivity INT, satisfaction INT,
  before_methods STRING, asked_analyst BOOLEAN,
  minutes_before DOUBLE, minutes_with_genie DOUBLE,
  minutes_saved DOUBLE COMMENT 'minutes_before - minutes_with_genie, floored at 0',
  analyst_minutes DOUBLE, trust INT, comments STRING
) COMMENT 'Genie ROI survey responses (anonymous)'"""


def run(statement: str, params: dict | None = None) -> None:
    with sql.connect(
        server_hostname=cfg.host,
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    ) as conn, conn.cursor() as cur:
        cur.execute(statement, params or {})


@st.cache_resource(show_spinner=False)
def ensure_table() -> str | None:
    """Create the responses table if needed. Returns an error message, or None."""
    try:
        run(DDL.format(table=TABLE))
        return None
    except Exception as e:  # noqa: BLE001
        return str(e)


def save(answers: dict) -> None:
    row = {c: answers.get(c) for c in COLUMNS}
    row["response_id"] = str(uuid.uuid4())
    row["submitted_at"] = datetime.now(timezone.utc)
    run(f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES ({', '.join(':' + c for c in COLUMNS)})", row)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
if not WAREHOUSE_ID:
    st.error("DATABRICKS_WAREHOUSE_ID is not set. Add a SQL warehouse resource to the app (see README).")
    st.stop()
if not re.fullmatch(r"[\w-]+\.[\w-]+\.[\w-]+", TABLE):
    st.error("Set GENIE_ROI_SURVEY_TABLE to <catalog>.<schema>.<table> in app.yaml (see README).")
    st.stop()
if err := ensure_table():
    st.error("The survey table is not available. Ask an admin to create it and grant the app access (see README).")
    st.code(err[:500])
    st.stop()

# ---------------------------------------------------------------------------
# Survey
# ---------------------------------------------------------------------------
st.title("📝 Genie survey")
st.write("Five minutes, anonymous: we don't record your name or email. Your answers help us measure the time "
         "Genie saves and improve it.")

if st.session_state.get("done"):
    st.success("Thank you! Your answers have been recorded.")
    st.stop()

st.write("**Which tools do you use?** Tick one or both.")
uses_code = st.checkbox("Genie Code: writing code or SQL in notebooks or the SQL editor")
uses_agents = st.checkbox("Genie: asking data questions in plain language")
if not (uses_code or uses_agents):
    st.stop()

with st.form("survey"):
    if uses_code:
        st.subheader("Genie Code")
        c_role = st.radio("A1. What is your role?", ["Data engineer", "Data scientist", "Analyst", "Other"],
                          index=None)
        c_frequency = st.radio("A2. How often do you use Genie Code?",
                               ["Several times an hour", "Daily", "Weekly", "Monthly", "Rarely"], index=None)
        c_where = st.radio("A3. Where do you use it?", ["SQL editor", "Notebooks", "Both"], index=None)
        c_use_cases = st.multiselect("A4. What do you mainly use it for?", [
            "Writing code", "Writing SQL queries", "Fixing errors", "Refactoring code", "Writing tests",
            "Looking up documentation", "Other"])
        c_hours = st.radio("A5. How many hours per week do you spend writing, fixing or reading code or SQL?",
                           list(CODING_HOURS), index=None)
        c_saved = st.radio("A6. On average, how much of that time does Genie Code save you?",
                           list(TIME_SAVED), index=None)
        c_productivity = st.select_slider("A7. Since using Genie Code, are you more productive? "
                                          "(1 = much less, 5 = much more)", SCALE, value=3)
        c_satisfaction = st.select_slider("A8. How satisfied are you with Genie Code's answers? "
                                          "(1 = not satisfied, 5 = extremely satisfied)", SCALE, value=3)
        c_comments = st.text_area("A9. Any other feedback on Genie Code?")

    if uses_agents:
        st.subheader("Genie")
        g_role = st.radio("B1. What is your department?",
                          ["Finance", "Retail", "Marketing", "Supply chain", "Management", "Data / IT", "Other"],
                          index=None)
        g_frequency = st.radio("B2. How often do you ask Genie questions?",
                               ["Daily", "Weekly", "Monthly", "Rarely"], index=None)
        g_before = st.multiselect("B3. Before Genie, how did you get these answers?", [
            ASKED_ANALYST, "Looked in an existing report or dashboard", "Built it in Excel",
            "I didn't get the answer"])
        g_min_before = st.radio("B4. Before Genie, how long did it take you on average to get an answer? "
                                "(your own time, not counting waiting)", list(MIN_BEFORE), index=None)
        g_min_with = st.radio("B5. How long does it take you with Genie?", list(MIN_WITH), index=None)
        g_analyst = st.radio("B6. If you asked an analyst, how much of their working time do you think it took?",
                             list(ANALYST_MIN), index=None, help="Skip if you never asked an analyst.")
        g_trust = st.select_slider("B7. Do you trust Genie's answers enough to make decisions? "
                                   "(1 = not at all, 5 = completely)", SCALE, value=3)
        g_comments = st.text_area("B8. What would make you use Genie more?")

    submitted = st.form_submit_button("Submit")

if submitted:
    missing = []
    if uses_code and None in (c_role, c_frequency, c_where, c_hours, c_saved):
        missing.append("Genie Code: A1, A2, A3, A5 and A6")
    if uses_agents and (None in (g_role, g_frequency, g_min_before, g_min_with) or not g_before):
        missing.append("Genie: B1 to B5")
    if missing:
        st.warning("Please answer " + "; ".join(missing) + ".")
        st.stop()
    # One row per tool, so the Genie ROI app can average each survey separately.
    if uses_code:
        save({
            "survey": "genie_code", "role": c_role, "frequency": c_frequency, "where_used": c_where,
            "use_cases": "; ".join(c_use_cases), "coding_hours": CODING_HOURS[c_hours],
            "time_saved_pct": TIME_SAVED[c_saved], "productivity": c_productivity,
            "satisfaction": c_satisfaction, "comments": c_comments.strip() or None,
        })
    if uses_agents:
        save({
            "survey": "genie_agents", "role": g_role, "frequency": g_frequency,
            "before_methods": "; ".join(g_before), "asked_analyst": ASKED_ANALYST in g_before,
            "minutes_before": MIN_BEFORE[g_min_before], "minutes_with_genie": MIN_WITH[g_min_with],
            "minutes_saved": max(MIN_BEFORE[g_min_before] - MIN_WITH[g_min_with], 0.0),
            "analyst_minutes": ANALYST_MIN[g_analyst] if g_analyst else None,
            "trust": g_trust, "comments": g_comments.strip() or None,
        })
    st.session_state.done = True
    st.rerun()
