# Databricks notebook source
# MAGIC %md
# MAGIC # Genie ROI - refresh aggregates
# MAGIC Rebuilds the four daily tables the app reads (last 400 days) from the system tables.
# MAGIC Scheduled daily by `databricks.yml`. The identity running this job needs `SELECT` on the system tables
# MAGIC and `CREATE TABLE` on the target schema.

# COMMAND ----------

import queries as q

dbutils.widgets.text("schema", "", "Target schema (catalog.schema)")
schema = dbutils.widgets.get("schema").strip()
if schema.count(".") != 1:
    raise ValueError("Set the `schema` parameter to <catalog>.<schema>")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
for name in q.DATASETS:
    spark.sql(q.materialize_sql(name, schema))
    print(f"{schema}.{name}: {spark.table(f'{schema}.{name}').count():,} rows")
