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
# Look and feel: a form-style page (header card, one white card per question)
# ---------------------------------------------------------------------------
ACCENT = "#6D5DFC"
st.markdown(f"""
<style>
  #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stHeader"] {{display: none;}}
  .block-container {{padding-top: 2rem; max-width: 760px;}}
  [data-testid="stForm"] {{border: none; padding: 0;}}
  [class*="st-key-q-"] {{
    background: #FFFFFF; border: 1px solid #DADCE0; border-radius: 8px; padding: 18px 24px 12px;
    margin-bottom: .25rem;
  }}
  .card {{background: #FFFFFF; border: 1px solid #DADCE0; border-radius: 8px; margin-bottom: 1rem; overflow: hidden;}}
  .card .band {{height: 10px; background: linear-gradient(90deg, {ACCENT}, #14B8A6);}}
  .card .body {{padding: 22px 24px 18px;}}
  .card h1 {{font-size: 2rem; font-weight: 500; margin: 0 0 .5rem; padding: 0;}}
  .card h2 {{font-size: 1.35rem; font-weight: 500; margin: 0; padding: 0;}}
  .card p {{color: #3C4043; margin: .25rem 0;}}
  .section {{border-left: 6px solid {ACCENT};}}
  .req {{color: #D93025;}}
  .q {{font-size: 1.02rem; font-weight: 500; color: #202124; margin-bottom: .1rem;}}
  .hint {{font-size: .85rem; color: #5F6368;}}
</style>
""", unsafe_allow_html=True)


def card(title: str, text: str = "", band: bool = False, section: bool = False, big: bool = False) -> None:
    tag = "h1" if big else "h2"
    st.markdown(
        f'<div class="card{" section" if section else ""}">{"<div class=band></div>" if band else ""}'
        f'<div class="body"><{tag}>{title}</{tag}>{text}</div></div>',
        unsafe_allow_html=True,
    )


def question(label: str, required: bool = True, hint: str = ""):
    """A white card holding one question; the widget inside uses a collapsed label."""
    st.session_state.q_count = st.session_state.get("q_count", 0) + 1
    box = st.container(key=f"q-{st.session_state.q_count}")
    box.markdown(f'<div class="q">{label}{" <span class=req>*</span>" if required else ""}</div>'
                 + (f'<div class="hint">{hint}</div>' if hint else ""), unsafe_allow_html=True)
    return box


def choice(label: str, options, required: bool = True, hint: str = "", horizontal: bool = False):
    return question(label, required, hint).radio(label, list(options), index=None, horizontal=horizontal,
                                                 label_visibility="collapsed")


def checkboxes(label: str, options, required: bool = True, hint: str = "Select all that apply.") -> list[str]:
    box = question(label, required, hint)
    return [o for i, o in enumerate(options) if box.checkbox(o, key=f"{label}-{i}")]


def scale(label: str, low: str, high: str, required: bool = False):
    box = question(label, required, f"1 = {low}, 5 = {high}")
    return box.radio(label, SCALE, index=None, horizontal=True, label_visibility="collapsed")


def text(label: str) -> str:
    return question(label, required=False).text_area(label, label_visibility="collapsed",
                                                     placeholder="Your answer")


HEADER = ('<p>Help us measure the time Genie saves you, and how to make it better.</p>'
          '<p class="hint">About 5 minutes · anonymous: we don\'t record your name or email.</p>'
          '<p class="hint"><span class="req">*</span> Required</p>')

# ---------------------------------------------------------------------------
# Survey
# ---------------------------------------------------------------------------
st.session_state.q_count = 0  # question cards are numbered afresh on every rerun

if st.session_state.get("done"):
    card("Genie survey", "<p>Your response has been recorded. Thank you!</p>", band=True, big=True)
    st.stop()

card("Genie survey", HEADER, band=True, big=True)

box = question("Which tools do you use?", hint="Tick one or both.")
uses_code = box.checkbox("Genie Code: writing code or SQL in notebooks or the SQL editor")
uses_agents = box.checkbox("Genie: asking data questions in plain language")
if not (uses_code or uses_agents):
    st.stop()

with st.form("survey", border=False):
    if uses_code:
        card("Genie Code", "<p>About writing code and SQL with Genie Code.</p>", section=True)
        c_role = choice("What is your role?", ["Data engineer", "Data scientist", "Analyst", "Other"])
        c_frequency = choice("How often do you use Genie Code?",
                             ["Several times an hour", "Daily", "Weekly", "Monthly", "Rarely"])
        c_where = choice("Where do you use it?", ["SQL editor", "Notebooks", "Both"])
        c_use_cases = checkboxes("What do you mainly use it for?", [
            "Writing code", "Writing SQL queries", "Fixing errors", "Refactoring code", "Writing tests",
            "Looking up documentation", "Other"], required=False)
        c_hours = choice("How many hours per week do you spend writing, fixing or reading code or SQL?",
                         CODING_HOURS)
        c_saved = choice("On average, how much of that time does Genie Code save you?", TIME_SAVED)
        c_productivity = scale("Since using Genie Code, are you more productive?", "much less", "much more")
        c_satisfaction = scale("How satisfied are you with Genie Code's answers?", "not satisfied",
                               "extremely satisfied")
        c_comments = text("Any other feedback on Genie Code?")

    if uses_agents:
        card("Genie", "<p>About asking data questions to Genie.</p>", section=True)
        g_role = choice("What is your department?",
                        ["Finance", "Retail", "Marketing", "Supply chain", "Management", "Data / IT", "Other"])
        g_frequency = choice("How often do you ask Genie questions?", ["Daily", "Weekly", "Monthly", "Rarely"])
        g_before = checkboxes("Before Genie, how did you get these answers?", [
            ASKED_ANALYST, "Looked in an existing report or dashboard", "Built it in Excel",
            "I didn't get the answer"])
        g_min_before = choice("Before Genie, how long did it take you on average to get an answer?", MIN_BEFORE,
                              hint="Your own time, not counting waiting.")
        g_min_with = choice("How long does it take you with Genie?", MIN_WITH)
        g_analyst = choice("If you asked an analyst, how much of their working time do you think it took?",
                           ANALYST_MIN, required=False, hint="Skip if you never asked an analyst.")
        g_trust = scale("Do you trust Genie's answers enough to make decisions?", "not at all", "completely")
        g_comments = text("What would make you use Genie more?")

    submitted = st.form_submit_button("Submit", type="primary")

if submitted:
    missing = []
    if uses_code and None in (c_role, c_frequency, c_where, c_hours, c_saved):
        missing.append("Genie Code")
    if uses_agents and (None in (g_role, g_frequency, g_min_before, g_min_with) or not g_before):
        missing.append("Genie")
    if missing:
        st.error(f"Please answer all required questions (*) in the {' and '.join(missing)} section.")
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
