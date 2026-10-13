"""SQL used by the app. Queries use these named parameters:
  :days   - lookback window in days
  :ws     - workspace id to filter on ('' = all workspaces)
  :humans - 1 = only identities that look like users (email), 0 = include service principals
"""

# ---------------------------------------------------------------------------
# Genie Code  (system.access.assistant_events)
# Only user-submitted interactions: chat, agent mode, inline assistant.
# Before 2026-05-07 the table also logged background requests (autocomplete,
# quick fixes...), so counts before that date are inflated.
# ---------------------------------------------------------------------------
_CODE_BASE = """
WITH e AS (
  SELECT CAST(event_date AS DATE) AS d, event_time, workspace_id, initiated_by AS user_email
  FROM system.access.assistant_events
  WHERE CAST(event_date AS DATE) >= date_sub(current_date(), :days)
    AND (:ws = '' OR workspace_id = :ws)
    AND (:humans = 0 OR initiated_by LIKE '%@%')
)
"""

CODE_KPIS = _CODE_BASE + """
SELECT COUNT(*) AS interactions,
       COUNT(DISTINCT user_email) AS active_users,
       COUNT(DISTINCT workspace_id) AS workspaces,
       COUNT(DISTINCT user_email, d) AS active_user_days
FROM e
"""

CODE_DAILY = _CODE_BASE + """
SELECT d AS date, COUNT(*) AS interactions, COUNT(DISTINCT user_email) AS active_users
FROM e GROUP BY d ORDER BY d
"""

CODE_MONTHLY = _CODE_BASE + """
, m AS (SELECT DISTINCT date_trunc('MONTH', d) AS month, user_email FROM e)
, first_seen AS (SELECT user_email, MIN(month) AS first_month FROM m GROUP BY user_email)
SELECT m.month,
       COUNT(DISTINCT m.user_email) AS monthly_active_users,
       COUNT(DISTINCT CASE WHEN f.first_month = m.month THEN m.user_email END) AS new_users,
       COUNT(DISTINCT CASE WHEN p.user_email IS NOT NULL THEN m.user_email END) AS returning_users
FROM m
JOIN first_seen f ON f.user_email = m.user_email
LEFT JOIN m p ON p.user_email = m.user_email AND p.month = add_months(m.month, -1)
GROUP BY m.month ORDER BY m.month
"""

CODE_BY_WORKSPACE = _CODE_BASE + """
SELECT workspace_id, COUNT(*) AS interactions, COUNT(DISTINCT user_email) AS active_users,
       ROUND(COUNT(*) / COUNT(DISTINCT user_email), 1) AS interactions_per_user
FROM e GROUP BY workspace_id ORDER BY interactions DESC
"""

CODE_TOP_USERS = _CODE_BASE + """
SELECT user_email, COUNT(*) AS interactions, COUNT(DISTINCT d) AS active_days, MAX(event_time) AS last_used
FROM e GROUP BY user_email ORDER BY interactions DESC LIMIT 50
"""

# ---------------------------------------------------------------------------
# Genie spaces  (system.access.audit, service_name = 'aibiGenie')
# ---------------------------------------------------------------------------
MESSAGE_ACTIONS = (
    "'createConversationMessage', 'genieCreateConversationMessage', "
    "'genieStartConversationMessage', 'createAgenticResponse', 'genieCreateAgenticResponse'"
)

_GENIE_BASE = f"""
WITH g AS (
  SELECT event_date AS d, event_time, CAST(workspace_id AS STRING) AS workspace_id,
         user_identity.email AS user_email, action_name,
         request_params['space_id'] AS space_id,
         request_params['conversation_id'] AS conversation_id,
         upper(request_params['feedback_rating']) AS rating,
         response.status_code AS status_code,
         action_name IN ({MESSAGE_ACTIONS}) AND response.status_code = 200 AS is_question,
         action_name IN ({MESSAGE_ACTIONS}) AND response.status_code <> 200 AS is_failed_question
  FROM system.access.audit
  WHERE service_name = 'aibiGenie'
    AND event_date >= date_sub(current_date(), :days)
    AND (:ws = '' OR CAST(workspace_id AS STRING) = :ws)
    AND (:humans = 0 OR user_identity.email LIKE '%@%')
    AND action_name IN ({MESSAGE_ACTIONS}, 'createSpace', 'updateConversationMessageFeedback',
                        'regenerateConversationMessage', 'cancelMessage', 'createInstruction',
                        'updateInstruction', 'createCuratedQuestion', 'updateCuratedQuestion',
                        'createEvaluationRun')
)
"""

# Observed feedback_rating values: THUMBS_UP / THUMBS_DOWN (GENIE_RATING_VALUES lists them).
_UP = "rating = 'THUMBS_UP'"
_DOWN = "rating = 'THUMBS_DOWN'"

GENIE_KPIS = _GENIE_BASE + f"""
SELECT COUNT_IF(is_question) AS questions,
       -- API conversation starts carry no conversation_id: each one is a new conversation
       COUNT(DISTINCT CASE WHEN is_question THEN conversation_id END)
         + COUNT_IF(is_question AND action_name = 'genieStartConversationMessage') AS conversations,
       COUNT(DISTINCT CASE WHEN is_question THEN user_email END) AS active_users,
       COUNT(DISTINCT CASE WHEN is_question THEN space_id END) AS active_spaces,
       COUNT_IF(action_name = 'createSpace') AS spaces_created,
       COUNT_IF(action_name = 'updateConversationMessageFeedback' AND {_UP}) AS thumbs_up,
       COUNT_IF(action_name = 'updateConversationMessageFeedback' AND {_DOWN}) AS thumbs_down,
       COUNT_IF(action_name = 'regenerateConversationMessage') AS regenerations,
       COUNT_IF(action_name = 'cancelMessage') AS cancellations,
       COUNT_IF(is_failed_question) AS failed_questions
FROM g
"""

GENIE_RATING_VALUES = _GENIE_BASE + """
SELECT rating, COUNT(*) AS n FROM g
WHERE action_name = 'updateConversationMessageFeedback' GROUP BY rating
"""

GENIE_DAILY = _GENIE_BASE + """
SELECT d AS date, COUNT_IF(is_question) AS questions,
       COUNT(DISTINCT CASE WHEN is_question THEN user_email END) AS active_users
FROM g GROUP BY d ORDER BY d
"""

GENIE_MONTHLY = _GENIE_BASE + """
, m AS (SELECT DISTINCT date_trunc('MONTH', d) AS month, user_email FROM g WHERE is_question)
, first_seen AS (SELECT user_email, MIN(month) AS first_month FROM m GROUP BY user_email)
SELECT m.month,
       COUNT(DISTINCT m.user_email) AS monthly_active_users,
       COUNT(DISTINCT CASE WHEN f.first_month = m.month THEN m.user_email END) AS new_users,
       COUNT(DISTINCT CASE WHEN p.user_email IS NOT NULL THEN m.user_email END) AS returning_users
FROM m
JOIN first_seen f ON f.user_email = m.user_email
LEFT JOIN m p ON p.user_email = m.user_email AND p.month = add_months(m.month, -1)
GROUP BY m.month ORDER BY m.month
"""

GENIE_BY_SPACE = _GENIE_BASE + f"""
SELECT workspace_id, space_id,
       COUNT_IF(is_question) AS questions,
       COUNT(DISTINCT CASE WHEN is_question THEN user_email END) AS users,
       -- API conversation starts carry no conversation_id: each one is a new conversation
       COUNT(DISTINCT CASE WHEN is_question THEN conversation_id END)
         + COUNT_IF(is_question AND action_name = 'genieStartConversationMessage') AS conversations,
       COUNT_IF(action_name = 'updateConversationMessageFeedback' AND {_UP}) AS thumbs_up,
       COUNT_IF(action_name = 'updateConversationMessageFeedback' AND {_DOWN}) AS thumbs_down,
       COUNT_IF(action_name IN ('createInstruction', 'updateInstruction', 'createCuratedQuestion',
                                'updateCuratedQuestion', 'createEvaluationRun')) AS curation_actions,
       MAX(CASE WHEN is_question THEN event_time END) AS last_question
FROM g WHERE space_id IS NOT NULL
GROUP BY workspace_id, space_id
HAVING COUNT_IF(is_question) > 0
ORDER BY questions DESC
"""

GENIE_TOP_USERS = _GENIE_BASE + """
SELECT user_email, COUNT(*) AS questions, COUNT(DISTINCT space_id) AS spaces,
       COUNT(DISTINCT d) AS active_days, MAX(event_time) AS last_question
FROM g WHERE is_question
GROUP BY user_email ORDER BY questions DESC LIMIT 50
"""

GENIE_CURATION = _GENIE_BASE + """
SELECT date_trunc('MONTH', d) AS month,
       COUNT_IF(action_name IN ('createInstruction', 'updateInstruction')) AS instruction_changes,
       COUNT_IF(action_name IN ('createCuratedQuestion', 'updateCuratedQuestion')) AS sample_or_benchmark_questions,
       COUNT_IF(action_name = 'createEvaluationRun') AS benchmark_runs
FROM g GROUP BY 1 ORDER BY 1
"""

# ---------------------------------------------------------------------------
# Genie-generated SQL  (system.query.history, query_source.genie_space_id)
# ---------------------------------------------------------------------------
GENIE_SQL_BY_SPACE = """
SELECT query_source.genie_space_id AS space_id,
       COUNT(*) AS queries,
       ROUND(100 * AVG(CASE WHEN execution_status = 'FINISHED' THEN 1 ELSE 0 END), 1) AS success_pct,
       ROUND(percentile(total_duration_ms, 0.5) / 1000, 1) AS p50_seconds,
       ROUND(percentile(total_duration_ms, 0.9) / 1000, 1) AS p90_seconds,
       ROUND(SUM(read_bytes) / POW(1024, 3), 2) AS gb_read
FROM system.query.history
WHERE query_source.genie_space_id IS NOT NULL
  AND start_time >= date_sub(current_date(), :days)
  AND (:ws = '' OR workspace_id = :ws)
GROUP BY 1 ORDER BY queries DESC
"""

# Genie shares warehouses with other workloads, so its compute cost is estimated
# as (Genie execution time / total execution time) x warehouse list cost.
# List prices only: negotiated discounts are not reflected.
GENIE_COST_ESTIMATE = """
WITH q AS (
  SELECT compute.warehouse_id AS warehouse_id,
         SUM(CASE WHEN query_source.genie_space_id IS NOT NULL THEN total_duration_ms ELSE 0 END) AS genie_ms,
         SUM(total_duration_ms) AS all_ms
  FROM system.query.history
  WHERE start_time >= date_sub(current_date(), :days)
    AND compute.warehouse_id IS NOT NULL
    AND (:ws = '' OR workspace_id = :ws)
  GROUP BY 1
  HAVING SUM(CASE WHEN query_source.genie_space_id IS NOT NULL THEN total_duration_ms ELSE 0 END) > 0
), c AS (
  SELECT u.usage_metadata.warehouse_id AS warehouse_id,
         SUM(u.usage_quantity * p.pricing.default) AS list_cost_usd
  FROM system.billing.usage u
  JOIN system.billing.list_prices p
    ON u.sku_name = p.sku_name AND u.cloud = p.cloud AND u.usage_unit = p.usage_unit
   AND u.usage_start_time >= p.price_start_time
   AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
  WHERE u.usage_date >= date_sub(current_date(), :days)
    AND u.usage_metadata.warehouse_id IS NOT NULL
    AND (:ws = '' OR u.workspace_id = :ws)
  GROUP BY 1
)
SELECT q.warehouse_id,
       ROUND(100 * q.genie_ms / q.all_ms, 1) AS genie_share_pct,
       ROUND(c.list_cost_usd, 2) AS warehouse_list_cost_usd,
       ROUND(c.list_cost_usd * q.genie_ms / q.all_ms, 2) AS genie_cost_estimate_usd
FROM q LEFT JOIN c ON q.warehouse_id = c.warehouse_id
ORDER BY genie_cost_estimate_usd DESC NULLS LAST
"""
