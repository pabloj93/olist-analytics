# PRD — dbt-sql-agent-powerbi

> Portfolio project: end-to-end analytics engineering on a real e-commerce dataset,
> orchestrated with dbt on Databricks, exposed through an AI chatbot and a Power BI dashboard.

---

## 1. Project Overview

### What

A production-style **analytics engineering** project that turns the public Olist
Brazilian e-commerce dataset into a curated, tested, documented analytical layer on
**Databricks**. The same curated marts power two consumer surfaces:

- A **conversational chatbot** (LLM → SQL → Databricks) reusing the frontend of the
  prior portfolio project `sql-agent`.
- A **Power BI Desktop** dashboard connected to the marts via ODBC.

### Why

This project exists to fill three gaps in the portfolio:

1. **Analytics Engineering signal** — demonstrate the modern data stack
   (dbt + cloud warehouse + tests + docs + snapshots + macros) at a senior level.
2. **Real warehouse signal** — show comfort with Databricks (Unity Catalog,
   serverless SQL warehouse), not only local DuckDB.
3. **BI signal** — pair the engineering work with a polished business-facing
   artifact (Power BI), which most analytics roles require.

### Success criteria

A reviewer can:

- Clone the repo, fill `.env`, run one ingestion script + `dbt build`, and end up
  with documented, tested marts on their own Databricks Free workspace **in under
  15 minutes**.
- Open the Power BI `.pbix`, refresh, and see a working dashboard.
- Open the chatbot, ask a natural-language question, and get a correct answer
  backed by SQL executed on Databricks.

---

## 2. Skills & Tools

### Core stack

| Layer | Tool | Why this choice |
|---|---|---|
| Transformation | **dbt-core** + `dbt-databricks` adapter | Industry-standard analytics engineering tool; free; integrates natively with Databricks. |
| Warehouse | **Databricks Free Edition** (serverless SQL warehouse + Unity Catalog) | Real lakehouse experience for the CV; free tier covers this scale; serverless avoids cluster management. |
| Ingestion | **Python** + `databricks-sdk` (`scripts/load_raw.py`) | Reproducible, one-command raw load; better signal than UI upload; minimal code. |
| Dataset | **Olist Brazilian E-Commerce** (Kaggle) + `product_category_name_translation` for EN labels | Rich star-schema candidates (orders, customers, sellers, products, payments, reviews, geolocation); marketplace structure tells a story; geolocation table enables map visuals in Power BI. |
| Chatbot frontend | **Reuse** `../sql-agent` React/Vite/TS frontend | DRY across the portfolio; shows ability to compose existing components. |
| Chatbot backend | **FastAPI** + `databricks-sql-connector` + LLM provider | Same pattern as `sql-agent` backend but pointed at Databricks marts. |
| Observability (chatbot) | **LangFuse** (free tier) | Token usage, latency, trace inspection — standard in production LLM apps. |
| BI | **Power BI Desktop** + ODBC connector to Databricks SQL warehouse | Desktop is free; `.pbix` versioned in repo; screenshots + short video demo embedded in README. |

### Why Databricks-only (no DuckDB target)

Decided in PRD Round 1: a single target keeps profiles and CI simpler and lets the
project credibly claim "built on Databricks" on the CV. Dev/prod separation will
be handled via **schema separation in the same Unity Catalog** (`dev_*`, `prod_*`)
through the custom `generate_schema_name` macro.

### Why these macros

Round 2 fixed two macros — kept tight to avoid over-engineering:

- `generate_schema_name` — controls dev vs prod schema naming; classic dbt pattern,
  expected in any senior interview.
- `pivot_payment_methods` — dynamic Jinja pivot of payment types into columns;
  demonstrates non-trivial Jinja and reuse across marts.

### Why exactly one snapshot

Round 2 fixed `snapshot_sellers` (SCD type 2 on city/state). Olist sellers have
low natural churn, so the seed file will include a controlled set of injected
changes to make the SCD output meaningful in the demo.

---

## 3. Key Features — Roadmap

### V1 — Core dbt project (ship first, no polish)

**Definition of Done**: reviewer runs `python scripts/load_raw.py` and
`dbt build`, both succeed; `dbt docs serve` opens; all tests pass.

- `scripts/load_raw.py` uploads the 9 Olist CSVs as raw tables to Unity Catalog
- `models/staging/` — one `stg_<source>.sql` per raw table (renaming, casting, light cleaning), all materialized as `view`
- `models/intermediate/` — joins and pre-aggregations that feed multiple marts (materialized as `view` or `ephemeral`)
- `models/marts/`:
  - `dim_date`
  - `dim_customer`
  - `dim_product`
  - `dim_seller`
  - `fct_orders`
  - `mart_customer_rfm`
- `snapshots/snapshot_sellers.sql` — SCD type 2 on city/state
- `macros/generate_schema_name.sql` + `macros/pivot_payment_methods.sql`
- Tests:
  - Built-in: `unique`, `not_null`, `accepted_values`, `relationships` on all dim keys + fct FKs
  - Custom generic test (e.g. `test_positive_values`) applied to monetary columns
- `dbt docs generate` produces a complete docs site (`models`, `sources`, `seeds`, `snapshots` all documented in `.yml`)
- `README.md` with quick-start ≤5 steps + mermaid architecture diagram

### V2 — Bonuses + UX polish

- **Bonus 1 — Chatbot**
  - New `backend/` FastAPI app with `databricks-sql-connector`
  - LLM converts NL question → SQL → executes on Databricks SQL warehouse
  - LangFuse tracing
  - Reuses the `../sql-agent` frontend (only env vars change)
- **Bonus 2 — Power BI dashboard**
  - `.pbix` connected via ODBC to the `prod_marts` schema
  - Pages: Executive overview, Geography (Brazil map via geolocation), Marketplace (sellers), Customer (RFM segments)
  - Screenshots + ~30s screen-capture video embedded in README
- **Bonus 3 — Public chatbot deploy**
  - HF Spaces deployment of the chatbot (frontend + FastAPI backend in one Docker image)
  - Single public URL the reviewer can hit without local setup

### V3 — Stretch goals

- GitHub Actions running `dbt build` on PR against a `ci_*` schema
- Evaluation harness for the chatbot (NL question → expected answer → pass/fail JSON, target ≥80%)

---

## 4. Audience & Constraints

### Audience

- **Recruiters & hiring managers** — should see the visual deliverables (Power BI screenshots, chatbot GIF, dbt docs link) in the README within 30 seconds.
- **Senior data / analytics engineers** — should be able to inspect `models/`, `macros/`, tests, and `dbt_project.yml` and recognize idiomatic, production-quality dbt.
- **The author (Pablo)** — should leave the project with hands-on Databricks + dbt experience to put on the CV.

### Hard constraints

| Constraint | Limit | Mitigation |
|---|---|---|
| Budget | **$0** | All tools chosen from free tiers only (dbt-core, Databricks Free, Power BI Desktop, HF Spaces). |
| Databricks Free Edition compute hours | Limited monthly serverless DBU credits | Auto-stop SQL warehouse at 5 min idle; materialize marts as `table` so PBI/chatbot reads don't trigger compute. |
| Time | ~8–10h core + ~6h bonuses | Strict V1 scope; bonuses live in V2; no polish before V1 ships. |
| Public exposure | Repo will be public | `.env` in `.gitignore` from day one; no AI co-authorship in commit messages; neutral phrasing in README (LLM, not vendor names). |
| Reproducibility | Reviewer must run end-to-end without contacting the author | All raw data from public Kaggle; `scripts/load_raw.py` is idempotent; `.env.example` documents every variable. |

### Non-goals (out of scope)

- Real-time / streaming ingestion (Auto Loader, Structured Streaming).
- ML models on top of the marts.
- Multi-target dbt profile (DuckDB + Databricks) — Databricks only.
- Production-grade chatbot guardrails (SQL injection prevention beyond parameterized exec, content moderation, rate limiting) — note in README as V3.
