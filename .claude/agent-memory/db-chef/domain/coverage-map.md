# Coverage map

Default cadence: 6 months for tenancy / auth / grants areas, 3 months for index and performance audits.

| Area | Last reviewed | Findings | Re-review due |
|---|---|---|---|
| schema `qbo` init: roles + grants (M1–M4) | 2026-09-25 | ANTI-001 (qa_reports_snapshot nullable keys, open) | 2027-03-25 |
| Vault token functions (M5) | 2026-09-25 | DEC-001 | 2027-03-25 |
| Index audit on `qbo` FK columns | 2026-09-25 (design-time) | `fact_gl` FKs unindexed, accepted by ADR-0003 at 3K txns | 2026-12-25 (or when volume passes ~50K lines) |
| Post-apply verification on `vosk.dev` (grants, advisors) | (not run — files not applied yet) | — | open |
