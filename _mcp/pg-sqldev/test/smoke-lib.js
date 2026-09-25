// @ts-check
/** Pure helpers of the smoke test, kept apart so they can be unit-tested without a database. */

/**
 * @typedef {{ _schema: string, _name: string, _seq_scan: number, _seq_tup_read: number, _idx_scan: number, _idx_tup_fetch: number }} CounterRow
 */

/**
 * Which user tables had their scan counters move between two readings.
 * A table that appears or disappears in between is reported too, never silently skipped.
 * @param {CounterRow[]} before
 * @param {CounterRow[]} after
 */
export function diffCounters(before, after) {
    const key = (/** @type {CounterRow} */ r) => `${r._schema}.${r._name}`;
    const prev = new Map(before.map((r) => [key(r), r]));
    /** @type {{ relation: string, seq_scan: number, seq_tup_read: number, idx_scan: number, idx_tup_fetch: number, note?: string }[]} */
    const moved = [];
    for (const a of after) {
        const b = prev.get(key(a));
        prev.delete(key(a));
        if (!b) {
            moved.push({ relation: key(a), seq_scan: 0, seq_tup_read: 0, idx_scan: 0, idx_tup_fetch: 0, note: 'new table during the run' });
            continue;
        }
        const d = {
            relation: key(a),
            seq_scan: Number(a._seq_scan) - Number(b._seq_scan),
            seq_tup_read: Number(a._seq_tup_read) - Number(b._seq_tup_read),
            idx_scan: Number(a._idx_scan) - Number(b._idx_scan),
            idx_tup_fetch: Number(a._idx_tup_fetch) - Number(b._idx_tup_fetch),
        };
        if (d.seq_scan || d.seq_tup_read || d.idx_scan || d.idx_tup_fetch) moved.push(d);
    }
    for (const k of prev.keys()) moved.push({ relation: k, seq_scan: 0, seq_tup_read: 0, idx_scan: 0, idx_tup_fetch: 0, note: 'table dropped during the run' });
    return moved;
}

/**
 * The scan-counter check cannot tell our sessions from anybody else's: the counters are global.
 * No movement proves the point. Movement on a busy server proves nothing either way, because
 * every statement this server sends is catalog-only by construction (asserted in the unit tests).
 * @param {ReturnType<typeof diffCounters>} moved
 * @param {number} otherSessions client sessions that are not ours
 */
export function counterVerdict(moved, otherSessions) {
    if (moved.length === 0) return { status: /** @type {const} */ ('PASS'), detail: 'no scan counter moved on any user table in scope' };
    if (otherSessions > 0) {
        return {
            status: /** @type {const} */ ('INCONCLUSIVE'),
            detail: `${moved.length} tables had counters move while ${otherSessions} other sessions were connected. The counters are global, so this cannot be attributed. Re-run at a quiet time.`,
        };
    }
    return { status: /** @type {const} */ ('FAIL'), detail: `${moved.length} tables had counters move and no other session was connected` };
}

/**
 * Pick the tracker materialized view out of an overview listing.
 * @param {{ schema: string, name: string, kind: string }[]} relations
 */
export function pickTrackerMatview(relations) {
    const mvs = relations.filter((r) => r.kind === 'm');
    const score = (/** @type {{ schema: string, name: string }} */ r) => (/track/i.test(r.name) ? 2 : 0) + (r.schema === 'portal' ? 1 : 0);
    const best = [...mvs].sort((a, b) => score(b) - score(a) || a.name.localeCompare(b.name))[0];
    if (!best) return null;
    const q = (/** @type {string} */ s) => (/^[a-z_][a-z0-9_$]*$/.test(s) ? s : `"${s.replace(/"/g, '""')}"`);
    return `${q(best.schema)}.${q(best.name)}`;
}
