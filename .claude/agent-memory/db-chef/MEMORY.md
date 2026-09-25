# db-chef — Memory Index

## Collaboration
_(none yet — user profile, feedback, project windows and external references go here as they surface)_

## Domain
<!-- format: <file> — N entries · <fresh>/<verified>/<aging> · hot: <top IDs by score> · <PREFIX>-NNN -->
<!-- inductive buckets: fresh = Last-verified <90d, verified = 90–270d, aging = >270d; durable entries do not decay by time -->
- [decisions.md](domain/decisions.md) — 1 entry · durable · hot: DEC-001 (advisory lock, not `for update`, for the Vault token) · DEC-NNN
- [lessons.md](domain/lessons.md) — 1 entry · durable · hot: LSN-001 (Write tool emits CRLF; normalize migration bytes to LF) · LSN-NNN
- [antipatterns.md](domain/antipatterns.md) — 1 entry · 1/0/0 · hot: ANTI-001 (silent row loss via nullable / unconstrained filter keys) · ANTI-NNN
- [coverage-map.md](domain/coverage-map.md) — first pass 2026-09-25 (design-time only; post-apply verification on `vosk.dev` still open)
- templates: `domain/templates/DEC-001.vault-advisory-lock.sql`
- not yet created (start lean): patterns.md, rls-recipes.md, candidates.md — open on first qualifying entry

## Open questions
- 2026-09-25: Does `postgres` on `vosk.dev` hold `update` on `vault.secrets`? Expected false (Supabase default grants). Read-only check: `select has_table_privilege('postgres', 'vault.secrets', 'update')`. If true, DEC-001 can revert to the row lock.
- 2026-09-25: `qa_reports_snapshot` nullable keys / no PK (ANTI-001 sighting 3) — spec-shaped, accepted in ADR-0003; revisit when V1 reconciliation is implemented.
