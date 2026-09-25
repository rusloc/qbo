<!-- next-id: LSN-002 -->

# Lessons

### LSN-001 · Migration files land as CRLF on this Windows box; `sed -i` under MSYS does not strip the CR · 2026-09-25
**Lesson:** The Write tool emits CRLF here; the repo wants UTF-8 no-BOM + LF for `supabase/migrations/*.sql`. `sed -i 's/\r$//'` in Git Bash left the CRs in place (text-mode rewrite). A Python byte-level `replace(b'\r\n', b'\n')` pass fixed it; verify with `count(b'\r') == 0`, `bytes[:3] != b'\xef\xbb\xbf'`.
**Context:** Writing F-05 M1–M5 (5 files). `git config core.autocrlf` is `false`, so nothing normalizes on commit — the bytes on disk are what gets committed and what `apply_migration` sends.
**Reversibility:** n/a (operational)
**Applied at:** `supabase/migrations/20260925213800..20260925214200_qbo_*.sql`
**Hits:** 1
**Tags:** encoding, crlf, windows, migrations, tooling
**Confidence:** high
**Last-verified:** 2026-09-25
**Trigger to revisit:** the Write tool starts honoring LF, or a `.gitattributes` `*.sql text eol=lf` rule is added (then the check becomes redundant but still cheap).
**Related:** DEC-001
**Status:** active
