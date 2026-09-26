# ferry — Memory Index

## Collaboration
- [Project: backend ready for PBI on synthetic data](project_backend_ready_for_pbi.md) — 2026-09-26 goal; vw_* as qbo_reader; expires 2026-10-26

## Domain
<!-- format: <file> — N entries · <fresh>/<verified>/<aging> · hot: <top-3 IDs by score> · <PREFIX>-NNN -->
<!-- buckets: fresh = Last-verified <60d, verified = 60–180d, aging = >180d -->
- [tool-quirks.md](domain/tool-quirks.md) — 3 entries (TOOL + folded SRC) · 3/0/0 · hot: TOOL-002, TOOL-001, SRC-001 · TOOL-NNN / SRC-NNN
- [decisions.md](domain/decisions.md) — 6 active · DEC-NNN · latest: DEC-006 (2026-09-26, sales account = ItemAccountRef first)
- [issues.md](domain/issues.md) — 6 open / 0 blocked / 1 resolved · ISS-NNN · oldest open: ISS-001 (2026-09-26)
- [candidates.md](domain/candidates.md) — 3 awaiting second hit (expire 2026-12-25)
- [pipeline-map.md](domain/pipeline-map.md) — 3 pipelines (all planned; none run on the DB yet) · last full review 2026-09-26
- journal.md — append-only work log (not auto-loaded)

## Open questions
- 2026-09-26: stmt_group / stmt_sort defaults OK? (ISS-001) — waiting on USER
- 2026-09-26: how to switch the warehouse from demo to sandbox data (ISS-002) — waiting on USER
- 2026-09-26: first `dbt build` results on vosk.dev (ISS-006) — waiting on USER run
