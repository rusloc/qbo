---
name: project-backend-ready-for-pbi
description: 2026-09-26 USER goal - warehouse filled with synthetic data and serve views readable by Power BI (qbo_reader), before real QBO data
metadata:
  type: project
---

USER goal 2026-09-26: backend fully ready = dataset built and Power BI reads `qbo.vw_*` as `qbo_reader`, so the USER can start the report. Synthetic (Track C) data goes into the warehouse first; the real extractor (qbo_sync) follows. No web report work today.

**Why:** unblock the Power BI build (bip lane) without waiting for the Intuit sandbox / real backfill.
**How to apply:** prioritise anything that keeps the vw_* interface stable (column names, date_key relationships); demo and real data must not be mixed in one schema (ISS-002). Remote writes (load, dbt build) are run by the USER, one approval each.
**Expires:** 2026-10-26
