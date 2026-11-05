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

st.set_page_config(page_title="Genie survey", page_icon="📝", layout="centered")

WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID")
TABLE = os.getenv("GENIE_ROI_SURVEY_TABLE", "").strip()

# Answer buckets and the midpoint stored for each, in the unit the Genie ROI app uses.
CODE_DAYS = {"Less than 1 day": 0.5, "1-2 days": 1.5, "3-4 days": 3.5, "Every working day": 5}
CODE_MIN_PER_DAY = {"Less than 15 min": 7.5, "15-30 min": 22.5, "30 min - 1 h": 45, "1-2 h": 90,
                    "More than 2 h": 150}
CODING_HOURS = {"Less than 5 h": 2.5, "5-10 h": 7.5, "10-20 h": 15, "20-30 h": 25, "More than 30 h": 32}
TIME_SAVED = {"0-10%": 5, "10-30%": 20, "30-50%": 40, "50-70%": 60, "More than 70%": 75}
QUESTIONS_PER_ANSWER = {"Just one": 1, "2 or 3": 2.5, "4 or 5": 4.5, "More than 5": 6}
MIN_BEFORE = {"Less than 5 min": 2.5, "5-15 min": 10, "15-30 min": 22.5, "30 min - 1 h": 45, "1-2 h": 90,
              "More than 2 h": 150}
MIN_WITH = {"Less than 2 min": 1, "2-5 min": 3.5, "5-15 min": 10, "15-30 min": 22.5, "More than 30 min": 40}
# Plain-language answers, stored as the share (%) they stand for.
WOULD_HAVE_LOOKED = {"Yes, almost all of them": 90, "Most of them": 70, "About half": 50, "Only a few": 25,
                     "Hardly any": 10}
ASKED_ANALYST = {"Never": 0, "Rarely": 10, "Sometimes": 30, "Often": 60, "Almost always": 90}
ANALYST_MIN = {"A few minutes": 7.5, "Up to 30 min": 20, "About an hour": 60, "Half a day": 240,
               "A day or more": 480}
SCALE = [1, 2, 3, 4, 5]

COLUMNS = [
    "response_id", "submitted_at", "survey", "role", "frequency",
    "code_minutes_per_day", "coding_hours", "time_saved_pct", "satisfaction",
    "questions_per_answer", "minutes_before", "minutes_with_genie", "substitution_pct", "analyst_share_pct",
    "analyst_minutes", "minutes_saved_per_question", "deflection_pct", "trust", "comments",
]
DDL = """CREATE TABLE IF NOT EXISTS {table} (
  response_id STRING, submitted_at TIMESTAMP, survey STRING COMMENT 'genie_code or genie_agents',
  role STRING, frequency STRING COMMENT 'Genie Code: days of use per week; Genie: how often',
  code_minutes_per_day DOUBLE COMMENT 'Genie Code: minutes saved on a day of use',
  coding_hours DOUBLE COMMENT 'Genie Code: hours of coding per week',
  time_saved_pct DOUBLE COMMENT 'Genie Code: share of coding time saved',
  satisfaction INT,
  questions_per_answer DOUBLE COMMENT 'Genie: questions asked to get one answer',
  minutes_before DOUBLE COMMENT 'Genie: own minutes per answer without Genie',
  minutes_with_genie DOUBLE COMMENT 'Genie: own minutes per answer with Genie',
  substitution_pct DOUBLE COMMENT 'Genie: share of answers that would have been looked for without Genie',
  analyst_share_pct DOUBLE COMMENT 'Genie: share of answers that would otherwise have been an analyst request',
  analyst_minutes DOUBLE COMMENT 'Genie: analyst minutes per request',
  minutes_saved_per_question DOUBLE COMMENT '(without - with) x substitution / questions per answer',
  deflection_pct DOUBLE COMMENT 'analyst_share_pct / questions per answer',
  trust INT, comments STRING
) COMMENT 'Genie ROI survey responses (anonymous), one row per tool and respondent'"""


@st.cache_resource(show_spinner=False)
def table_state() -> dict:
    """Shared by all sessions of this app process: has the table been checked yet?"""
    return {"checked": False}


def save(rows: list[dict]) -> None:
    """Insert one row per tool with a single connection and statement.

    The table is created on the first save of the app process, not at page load, so the form shows at once
    even when the warehouse is still starting.
    """
    # Imported here, not at the top: the SQL connector and auth setup are slow and only needed on submit.
    from databricks import sql
    from databricks.sdk.core import Config

    cfg = Config()
    stamp, params, values = datetime.now(timezone.utc), {}, []
    for i, answers in enumerate(rows):
        row = {c: answers.get(c) for c in COLUMNS} | {"response_id": str(uuid.uuid4()), "submitted_at": stamp}
        params |= {f"{c}_{i}": row[c] for c in COLUMNS}
        values.append("(" + ", ".join(f":{c}_{i}" for c in COLUMNS) + ")")
    with sql.connect(
        server_hostname=cfg.host,
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    ) as conn, conn.cursor() as cur:
        state = table_state()
        if not state["checked"]:
            try:
                cur.execute(DDL.format(table=TABLE))
            except Exception:  # noqa: BLE001 - the app may only have MODIFY on an existing table
                pass
            state["checked"] = True
        cur.execute(f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES {', '.join(values)}", params)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
if not WAREHOUSE_ID:
    st.error("DATABRICKS_WAREHOUSE_ID is not set. Add a SQL warehouse resource to the app (see README).")
    st.stop()
if not re.fullmatch(r"[\w-]+\.[\w-]+\.[\w-]+", TABLE):
    st.error("Set GENIE_ROI_SURVEY_TABLE to <catalog>.<schema>.<table> in app.yaml (see README).")
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
        c_days = choice("On how many days per week do you use Genie Code?", CODE_DAYS)
        c_min_day = choice("On a day you use Genie Code, how much time does it save you in total?",
                           CODE_MIN_PER_DAY, hint="Compared with doing the same work without it.")
        c_hours = choice("How many hours per week do you spend writing, fixing or reading code or SQL?",
                         CODING_HOURS)
        c_saved = choice("On average, what share of that time does Genie Code save you?", TIME_SAVED)
        c_satisfaction = scale("How satisfied are you with Genie Code's answers?", "not satisfied",
                               "extremely satisfied")
        c_comments = text("Anything else about Genie Code?")

    if uses_agents:
        card("Genie", "<p>About asking data questions to Genie.</p>", section=True)
        g_role = choice("What is your department?",
                        ["Finance", "Retail", "Marketing", "Supply chain", "Management", "Data / IT", "Other"])
        g_frequency = choice("How often do you use Genie?", ["Daily", "Weekly", "Monthly", "Rarely"])
        g_qpa = choice("How many questions do you usually ask Genie before you have the answer you need?",
                       QUESTIONS_PER_ANSWER)
        g_with = choice("How long does it usually take you to get that answer with Genie?", MIN_WITH)
        g_before = choice("Before Genie, how long did it take you to get the same kind of answer?", MIN_BEFORE,
                          hint="Searching reports, building it in Excel, writing a request... "
                               "Not counting time spent waiting for someone else.")
        g_subst = choice("If Genie didn't exist, would you still have looked for these answers?",
                         WOULD_HAVE_LOOKED, hint="Some questions you only ask because Genie makes it easy.")
        g_asked = choice("Before Genie, how often would you have asked an analyst or the data team for this "
                         "kind of answer?", ASKED_ANALYST)
        g_analyst_min = choice("When you asked an analyst, roughly how much of their time do you think it took?",
                               ANALYST_MIN, required=False, hint="Skip if you never asked an analyst.")
        g_trust = scale("Do you trust Genie's answers enough to make decisions?", "not at all", "completely")
        g_comments = text("What would make you use Genie more?")

    submitted = st.form_submit_button("Submit", type="primary")

if submitted:
    missing = []
    if uses_code and None in (c_role, c_days, c_min_day, c_hours, c_saved):
        missing.append("Genie Code")
    if uses_agents and None in (g_role, g_frequency, g_qpa, g_with, g_before, g_subst, g_asked):
        missing.append("Genie")
    if missing:
        st.error(f"Please answer all required questions (*) in the {' and '.join(missing)} section.")
        st.stop()
    # One row per tool, so the Genie ROI app can average each survey separately.
    rows = []
    if uses_code:
        rows.append({
            "survey": "genie_code", "role": c_role, "frequency": c_days,
            "code_minutes_per_day": CODE_MIN_PER_DAY[c_min_day], "coding_hours": CODING_HOURS[c_hours],
            "time_saved_pct": TIME_SAVED[c_saved], "satisfaction": c_satisfaction,
            "comments": c_comments.strip() or None,
        })
    if uses_agents:
        qpa, subst = QUESTIONS_PER_ANSWER[g_qpa], WOULD_HAVE_LOOKED[g_subst]
        before, with_genie = MIN_BEFORE[g_before], MIN_WITH[g_with]
        rows.append({
            "survey": "genie_agents", "role": g_role, "frequency": g_frequency,
            "questions_per_answer": qpa, "minutes_before": before, "minutes_with_genie": with_genie,
            "substitution_pct": subst, "analyst_share_pct": ASKED_ANALYST[g_asked],
            "analyst_minutes": ANALYST_MIN[g_analyst_min] if g_analyst_min else None,
            # Per question, because the Genie ROI app multiplies by the number of questions asked. Answers
            # people would not have looked for without Genie are valued at zero.
            "minutes_saved_per_question": max(before - with_genie, 0.0) * subst / 100 / qpa,
            "deflection_pct": ASKED_ANALYST[g_asked] / qpa,
            "trust": g_trust, "comments": g_comments.strip() or None,
        })
    try:
        with st.spinner("Saving your answers..."):
            save(rows)
    except Exception as e:  # noqa: BLE001
        st.error("Sorry, your answers could not be saved. Please try again in a minute, or contact the survey "
                 "owner if it keeps failing.")
        print(f"Survey save failed: {e}", flush=True)
        st.stop()
    st.session_state.done = True
    st.rerun()
