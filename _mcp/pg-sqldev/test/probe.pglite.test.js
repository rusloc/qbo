// @ts-check
/**
 * Dry run of the probe (A1) and unit tests of the smoke helpers (A8) without a real database.
 * Proves the probe SQL parses on a real engine, stays inside its query budget, reads no user
 * table, and renders a report. The real findings need the real server.
 */
import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { PGlite } from '@electric-sql/pglite';
import { loadConfig } from '../src/config.js';
import { createDb } from '../src/db.js';
import { createCache } from '../src/cache.js';
import { runProbe, renderProbe } from '../scripts/probe.js';
import { diffCounters, counterVerdict, pickTrackerMatview } from './smoke-lib.js';
import { loadSql } from '../src/sql.js';

/** @type {PGlite} */
let pg;
/** @type {string[]} */
const wire = [];

before(async () => {
    pg = new PGlite();
    await pg.exec(`
        create schema portal;
        create table public.sql_source (_report text not null, _page text not null, _code text, _updated timestamptz, unique (_report, _page));
        insert into public.sql_source values ('COMS', 'EK VIEW', 'select 1', now());
        create table portal.freight_unit (id bigint primary key, serial_no text);
        insert into portal.freight_unit select g, 'FU' || g from generate_series(1, 100) g;
        create table portal.never_analyzed (id int);
        create materialized view portal.tracker_mv as select f.id _id from portal.freight_unit f;
        analyze public.sql_source;
        analyze portal.freight_unit;
    `);
});
after(async () => {
    await pg.close();
});

function makeCtx() {
    const config = loadConfig({ envFile: 'Z:/none.env', env: { PG_SCHEMAS: 'public,portal,portal_dev' } });
    const driver = {
        connect: async () => ({
            /** @param {string | { text: string, values?: unknown[] }} q */
            query: async (q) => {
                if (typeof q === 'string') {
                    wire.push(q);
                    await pg.exec(q);
                    return { rows: [] };
                }
                wire.push(q.text);
                return { rows: /** @type {any[]} */ ((await pg.query(q.text, /** @type {any[]} */ (q.values ?? []))).rows) };
            },
            release() {},
        }),
        end: async () => {},
    };
    return { config, db: createDb(config, { driver }), cache: createCache({ ttlMs: 60_000, identity: 'probe-test' }), version: 'test' };
}

describe('probe dry run (A1)', () => {
    test('stays inside ten catalog queries and reads no user table', async () => {
        wire.length = 0;
        const report = await runProbe(makeCtx());
        assert.ok(report.catalog_queries <= 10, `queries = ${report.catalog_queries}`);
        const statements = wire.filter((w) => !/^(begin transaction read only|rollback)/.test(w));
        for (const s of statements) {
            const sql = s.replace(/--.*$/gm, '');
            assert.doesNotMatch(sql, /\b(from|join)\s+(public|portal|portal_dev)\./i, 'no statement reads a user table');
        }
        assert.equal(wire.filter((w) => w === 'rollback').length, wire.filter((w) => w.startsWith('begin transaction read only')).length, 'every transaction was rolled back');
    });

    test('records the facts the plan branches on', async () => {
        const r = await runProbe(makeCtx());
        assert.equal(r.guards.transaction_read_only, 'on');
        assert.equal(r.citus.version, null);
        assert.equal(r.pg_stat_statements.version, null);
        assert.equal(r.totals.relations, 4);
        assert.equal(r.totals.tables_and_matviews, 4);
        assert.ok(r.totals.never_analyzed >= 1);
        assert.ok(r.sql_source && 'columns' in r.sql_source);
        assert.deepEqual(/** @type {any} */ (r.sql_source).columns.map((/** @type {any} */ c) => c.column), ['_report', '_page', '_code', '_updated']);
        assert.match(/** @type {any} */ (r.sql_source).constraints.join(' '), /UNIQUE \(_report, _page\)/);
        assert.deepEqual('relations' in r.overview ? r.overview.matviews : null, ['portal.tracker_mv']);
        assert.ok(r.activity.ok);
    });

    test('turns facts into findings', async () => {
        const r = await runProbe(makeCtx());
        const all = r.findings.join('\n');
        assert.match(all, /Schema "portal_dev" does not exist/);
        assert.match(all, /pg_stat_statements is not installed: drop top_queries/);
        assert.match(all, /superuser/);
        assert.doesNotMatch(all, /column_profile \(C1\) should move forward/, 'empty and never-analyzed tables are not a statistics gap');
        assert.equal(r.totals.non_empty, 2, "sql_source and freight_unit; the matview and one table were never analyzed");
        assert.equal(r.totals.non_empty_without_stats, 0);
    });

    test('renders a summary with no secret in it', async () => {
        const ctx = makeCtx();
        Object.defineProperty(ctx.config, 'password', { value: 'TOPSECRET123', enumerable: false });
        const r = await runProbe(ctx);
        const text = renderProbe(r);
        assert.match(text, /pg-sqldev probe · .* catalog queries · .* no user table read/);
        assert.match(text, /public\.sql_source: _report text, _page text, _code text, _updated timestamp with time zone/);
        assert.match(text, /findings that change the build:/);
        assert.doesNotMatch(text + JSON.stringify(r), /TOPSECRET123/);
    });

    test('the smoke counter query runs and returns one row per user table', async () => {
        const ctx = makeCtx();
        const rows = await ctx.db.readOnly((tx) => tx.query('smoke-scan-counters', loadSql('smoke-scan-counters'), [ctx.config.schemas]));
        assert.deepEqual(rows.map((r) => `${r._schema}.${r._name}`).sort(), ['portal.freight_unit', 'portal.never_analyzed', 'portal.tracker_mv', 'public.sql_source']);
        assert.equal(typeof rows[0]._seq_scan, 'number');
    });
});

describe('smoke helpers (A8)', () => {
    const row = (/** @type {string} */ n, seq = 0, idx = 0) => ({ _schema: 'portal', _name: n, _seq_scan: seq, _seq_tup_read: seq * 10, _idx_scan: idx, _idx_tup_fetch: idx });

    test('nothing moved', () => assert.deepEqual(diffCounters([row('a', 5, 2), row('b')], [row('a', 5, 2), row('b')]), []));
    test('a moved counter is reported with its delta', () => {
        const moved = diffCounters([row('a', 5, 2)], [row('a', 7, 2)]);
        assert.equal(moved.length, 1);
        assert.equal(moved[0].relation, 'portal.a');
        assert.equal(moved[0].seq_scan, 2);
        assert.equal(moved[0].seq_tup_read, 20);
    });
    test('tables that appear or vanish are reported, not skipped', () => {
        const moved = diffCounters([row('gone')], [row('new')]);
        assert.deepEqual(moved.map((m) => m.note).sort(), ['new table during the run', 'table dropped during the run']);
    });
    test('verdicts: quiet pass, busy inconclusive, quiet fail', () => {
        assert.equal(counterVerdict([], 12).status, 'PASS');
        const moved = diffCounters([row('a', 1)], [row('a', 2)]);
        assert.equal(counterVerdict(moved, 3).status, 'INCONCLUSIVE');
        assert.equal(counterVerdict(moved, 0).status, 'FAIL');
    });
    test('tracker matview pick prefers "track" in portal and quotes when needed', () => {
        assert.equal(pickTrackerMatview([]), null);
        assert.equal(
            pickTrackerMatview([
                { schema: 'public', name: 'mv_other', kind: 'm' },
                { schema: 'portal_dev', name: 'tracker_mv', kind: 'm' },
                { schema: 'portal', name: 'tracker_mv', kind: 'm' },
                { schema: 'portal', name: 'freight_unit', kind: 'r' },
            ]),
            'portal.tracker_mv',
        );
        assert.equal(pickTrackerMatview([{ schema: 'portal', name: 'TrackerView', kind: 'm' }]), 'portal."TrackerView"');
    });
});
