"""SQL used by the app and by the refresh job.

The app works from four small daily datasets and computes every KPI from them in pandas:

  genie_daily      Genie spaces activity per day x workspace x space x user  (system.access.audit)
  code_daily       Genie Code activity per day x workspace x user            (system.access.assistant_events)
  genie_sql_daily  Genie-generated SQL per day x workspace x space           (system.query.history)
  warehouse_daily  Genie vs total execution time and list cost per warehouse (system.query.history, system.billing)

Each dataset is either computed live from the system tables (`live_sql`) or read from a table materialized by
the daily refresh job (`materialize_sql` / `read_sql`). Queries take these named parameters:
  :days   - lookback window in days
  :ws     - workspace id to filter on ('' = all workspaces)
  :humans - 1 = only identities that look like users (email), 0 = include service principals
"""

RETENTION_DAYS = 400  # history kept by the refresh job

QUESTION_ACTIONS = [
    "createConversationMessage",
    "genieCreateConversationMessage",
    "genieStartConversationMessage",
    "createAgenticResponse",
    "genieCreateAgenticResponse",
]
GENIE_ACTIONS = QUESTION_ACTIONS + [
    "createSpace",
    "updateConversationMessageFeedback",
    "regenerateConversationMessage",
    "cancelMessage",
    "createInstruction",
    "updateInstruction",
    "createCuratedQuestion",
    "updateCuratedQuestion",
    "createEvaluationRun",
]


def _in(values: list[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _ws(col: str, live: bool) -> str:
    return f"AND (:ws = '' OR CAST({col} AS STRING) = :ws)" if live else ""


def genie_daily(since: str, live: bool) -> str:
    q, ok = f"action_name IN ({_in(QUESTION_ACTIONS)})", "response.status_code = 200"
    humans = "AND (:humans = 0 OR user_identity.email LIKE '%@%')" if live else ""
    return f"""
SELECT event_date AS d,
       CAST(workspace_id AS STRING) AS workspace_id,
       request_params['space_id'] AS space_id,
       user_identity.email AS user_email,
       COUNT_IF({q} AND {ok}) AS questions,
       COUNT_IF({q} AND NOT {ok}) AS failed_questions,
       -- API conversation starts carry no conversation_id: each one is a new conversation
       COUNT(DISTINCT CASE WHEN {q} AND {ok} THEN request_params['conversation_id'] END)
         + COUNT_IF(action_name = 'genieStartConversationMessage' AND {ok}) AS conversations,
       COUNT_IF(action_name = 'updateConversationMessageFeedback'
                AND upper(request_params['feedback_rating']) = 'THUMBS_UP') AS thumbs_up,
       COUNT_IF(action_name = 'updateConversationMessageFeedback'
                AND upper(request_params['feedback_rating']) = 'THUMBS_DOWN') AS thumbs_down,
       COUNT_IF(action_name = 'regenerateConversationMessage') AS regenerations,
       COUNT_IF(action_name = 'cancelMessage') AS cancellations,
       COUNT_IF(action_name = 'createSpace') AS spaces_created,
       COUNT_IF(action_name IN ('createInstruction', 'updateInstruction')) AS instruction_changes,
       COUNT_IF(action_name IN ('createCuratedQuestion', 'updateCuratedQuestion')) AS sample_or_benchmark_questions,
       COUNT_IF(action_name = 'createEvaluationRun') AS benchmark_runs,
       MAX(event_time) AS last_event
FROM system.access.audit
WHERE service_name = 'aibiGenie'
  AND action_name IN ({_in(GENIE_ACTIONS)})
  AND event_date >= date_sub(current_date(), {since})
  {_ws("workspace_id", live)}
  {humans}
GROUP BY ALL
"""


# Only user-submitted interactions: chat, agent mode, inline assistant. Before 2026-05-07 the table also logged
# background requests (autocomplete, quick fixes...), so counts before that date are inflated.
def code_daily(since: str, live: bool) -> str:
    humans = "AND (:humans = 0 OR initiated_by LIKE '%@%')" if live else ""
    return f"""
SELECT CAST(event_date AS DATE) AS d, workspace_id, initiated_by AS user_email,
       COUNT(*) AS interactions, MAX(event_time) AS last_event
FROM system.access.assistant_events
WHERE CAST(event_date AS DATE) >= date_sub(current_date(), {since})
  {_ws("workspace_id", live)}
  {humans}
GROUP BY ALL
"""


def genie_sql_daily(since: str, live: bool) -> str:
    return f"""
SELECT CAST(start_time AS DATE) AS d, workspace_id, query_source.genie_space_id AS space_id,
       COUNT(*) AS queries,
       COUNT_IF(execution_status = 'FINISHED') AS finished,
       COUNT_IF(total_duration_ms > 10000) AS slow_queries,
       SUM(total_duration_ms) AS total_ms,
       SUM(read_bytes) AS read_bytes
FROM system.query.history
WHERE query_source.genie_space_id IS NOT NULL
  AND start_time >= date_sub(current_date(), {since})
  {_ws("workspace_id", live)}
GROUP BY ALL
"""


# Genie shares warehouses with other workloads, so its compute cost is estimated as
# (Genie execution time / total execution time) x warehouse list cost. Negotiated discounts are not reflected.
def warehouse_daily(since: str, live: bool) -> str:
    genie_ms = "SUM(CASE WHEN query_source.genie_space_id IS NOT NULL THEN total_duration_ms ELSE 0 END)"
    return f"""
WITH q AS (
  SELECT CAST(start_time AS DATE) AS d, workspace_id, compute.warehouse_id AS warehouse_id,
         {genie_ms} AS genie_ms, SUM(total_duration_ms) AS all_ms
  FROM system.query.history
  WHERE compute.warehouse_id IS NOT NULL
    AND start_time >= date_sub(current_date(), {since})
    {_ws("workspace_id", live)}
  GROUP BY ALL
  HAVING {genie_ms} > 0
), c AS (
  SELECT u.usage_date AS d, u.workspace_id, u.usage_metadata.warehouse_id AS warehouse_id,
         SUM(u.usage_quantity * p.pricing.default) AS list_cost_usd
  FROM system.billing.usage u
  JOIN system.billing.list_prices p
    ON u.sku_name = p.sku_name AND u.cloud = p.cloud AND u.usage_unit = p.usage_unit
   AND u.usage_start_time >= p.price_start_time
   AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
  WHERE u.usage_metadata.warehouse_id IS NOT NULL
    AND u.usage_date >= date_sub(current_date(), {since})
    {_ws("u.workspace_id", live)}
  GROUP BY ALL
)
SELECT q.d, q.workspace_id, q.warehouse_id, q.genie_ms, q.all_ms, c.list_cost_usd
FROM q LEFT JOIN c ON q.d = c.d AND q.workspace_id = c.workspace_id AND q.warehouse_id = c.warehouse_id
"""


DATASETS = {
    "genie_daily": (genie_daily, True),  # (source, has a user_email column)
    "code_daily": (code_daily, True),
    "genie_sql_daily": (genie_sql_daily, False),
    "warehouse_daily": (warehouse_daily, False),
}


def live_sql(name: str) -> str:
    source, _ = DATASETS[name]
    return source(":days", live=True)


def materialize_sql(name: str, schema: str) -> str:
    source, _ = DATASETS[name]
    return f"CREATE OR REPLACE TABLE {schema}.{name} AS {source(str(RETENTION_DAYS), live=False)}"


def read_sql(name: str, schema: str) -> str:
    _, has_user = DATASETS[name]
    humans = "AND (:humans = 0 OR user_email LIKE '%@%')" if has_user else ""
    return f"""
SELECT * FROM {schema}.{name}
WHERE d >= date_sub(current_date(), :days)
  AND (:ws = '' OR workspace_id = :ws)
  {humans}
"""
