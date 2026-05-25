# dbt-sql-agent-powerbi

> Analytics engineering portfolio project: Olist Brazilian e-commerce dataset → Databricks (dbt) → Power BI dashboard + AI chatbot.

**Status:** V1 in progress.

See [PRD.md](PRD.md) for full scope, roadmap, and design decisions.

## Stack

- **Transformation:** dbt-core + dbt-databricks adapter
- **Warehouse:** Databricks Free Edition (Unity Catalog + serverless SQL warehouse)
- **Ingestion:** Python `databricks-sdk` (one-shot, idempotent)
- **BI:** Power BI Desktop (V2 — `.pbix` + screenshots + screen-capture demo)
- **Chatbot:** FastAPI + LLM + `databricks-sql-connector` (V2 — frontend reused from sister project `sql-agent`)

## Quick start

_To be filled when V1 is functional. End goal: reviewer runs `python scripts/load_raw.py` + `dbt build` and gets all tests green in under 15 minutes._

## Layout

```
.
├── PRD.md                      Project requirements & roadmap
├── dbt/                        dbt project (models, macros, snapshots, tests)
├── ingestion/scripts/          Raw CSV → Unity Catalog upload
├── backend/                    V2 — chatbot FastAPI backend
├── powerbi/                    V2 — Power BI .pbix + visual assets
└── docs/                       Architecture diagrams, extra docs
```
