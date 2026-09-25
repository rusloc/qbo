#!/usr/bin/env node
// @ts-check
/**
 * Build step A8: the acceptance run. Needs the real database (.env filled in).
 *
 *     node test/smoke.js
 *
 * Drives the real server process over stdio, exactly as Claude Code will, and checks the four
 * "minimum impact" criteria of the plan:
 *   1. scan counters in pg_stat_user_tables do not move across all increment-1 tool calls
 *   2. a warm-cache call makes no database round trip (the server's own query counter)
 *   3. 30 s after the last call no session named mcp-pg-sqldev is open
 *   4. no increment-1 tool call issues more than three catalog queries
 * plus the functional checks of A5 to A7. Takes about 40 s, most of it waiting for check 3.
 *
 * A second, separate connection named "mcp-pg-sqldev-smoke" observes from outside. It follows the
 * same guards and reads statistics views only. Run this BEFORE registering the server in
 * .mcp.json: a registered, running server has sessions of its own and would blur check 3.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { loadConfig, notReadyMessage, APP_NAME } from '../src/config.js';
import { createDb, explainDbError } from '../src/db.js';
import { loadSql } from '../src/sql.js';
import { diffCounters, counterVerdict, pickTrackerMatview } from './smoke-lib.js';

const SERVER = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'index.js');
const MAX_QUERIES_PER_CALL = 3;
const OVERVIEW_BUDGET = 25 * 1024;

const config = loadConfig();
if (!config.ready) {
    console.error(notReadyMessage(config));
    process.exit(2);
}

/** @type {{ check: string, status: 'PASS' | 'FAIL' | 'INCONCLUSIVE', detail: string }[]} */
const checks = [];
/** @type {{ call: string, ms: number, catalog_queries: number, bytes: number }[]} */
const calls = [];
/**
 * @param {string} check
 * @param {boolean | 'INCONCLUSIVE'} ok
 * @param {string} detail
 */
const record = (check, ok, detail) => {
    const status = ok === 'INCONCLUSIVE' ? 'INCONCLUSIVE' : ok ? 'PASS' : 'FAIL';
    checks.push({ check, status, detail });
    console.error(`  ${status.padEnd(12)} ${check} · ${detail}`);
};

const observer = createDb(config, { applicationName: `${APP_NAME}-smoke` });
const readCounters = () => observer.readOnly((tx) => tx.query('smoke-scan-counters', loadSql('smoke-scan-counters'), [config.schemas]));
const readActivity = async () => (await observer.readOnly((tx) => tx.query('probe-activity', loadSql('probe-activity'), [APP_NAME])))[0];

/** @type {Client | null} */
let client = null;
let exitCode = 0;
try {
    console.error(`pg-sqldev smoke · ${config.database}@${config.host}:${config.port} as ${config.user}`);
    const countersBefore = await readCounters();
    const directCount = (
        await observer.readOnly((tx) =>
            tx.query(
                'smoke-direct-count',
                `select
     count(*)::int                                                              _relations
from pg_catalog.pg_class c
join pg_catalog.pg_namespace n on n.oid = c.relnamespace
where 1=1
    and n.nspname = any($1::text[])
    and c.relkind in ('r', 'p', 'v', 'm', 'f')`,
                [config.schemas],
            ),
        )
    )[0]._relations;

    const transport = new StdioClientTransport({ command: process.execPath, args: [SERVER], env: /** @type {Record<string, string>} */ ({ ...process.env }), stderr: 'inherit' });
    client = new Client({ name: 'pg-sqldev-smoke', version: '0.0.0' });
    await client.connect(transport);

    /** Server-side query counter, read through a cached connection_info call (zero queries itself). */
    const serverQueries = async () => {
        const r = await /** @type {Client} */ (client).callTool({ name: 'connection_info', arguments: { format: 'json' } });
        return JSON.parse(/** @type {any[]} */ (r.content)[0].text).process.catalog_queries;
    };
    /**
     * @param {string} label
     * @param {string} name
     * @param {Record<string, unknown>} args
     */
    const timed = async (label, name, args) => {
        const q0 = label === 'connection_info cold' ? 0 : await serverQueries();
        const t0 = Date.now();
        const r = await /** @type {Client} */ (client).callTool({ name, arguments: args });
        const ms = Date.now() - t0;
        const text = String(/** @type {any[]} */ (r.content)[0]?.text ?? '');
        const q1 = await serverQueries();
        const entry = { call: label, ms, catalog_queries: q1 - q0, bytes: Buffer.byteLength(text) };
        calls.push(entry);
        console.error(`  call         ${label} · ${ms} ms · ${entry.catalog_queries} catalog queries · ${entry.bytes} bytes${r.isError ? ' · ERROR' : ''}`);
        return { text, isError: r.isError === true, ...entry };
    };

    // ---- A5 connection_info ------------------------------------------------------------------
    const tools = (await client.listTools()).tools.map((t) => t.name).sort();
    record('tools/list', tools.join(',') === 'connection_info,describe_table,schema_overview', tools.join(', '));

    const info = await timed('connection_info cold', 'connection_info', { refresh: true, format: 'json' });
    if (info.isError) throw new Error(`connection_info failed:\n${info.text}`);
    const infoData = JSON.parse(info.text);
    record('guards in force', infoData.guards.transaction_read_only === 'on', `read_only=${infoData.guards.transaction_read_only} statement_timeout=${infoData.guards.statement_timeout} lock_timeout=${infoData.guards.lock_timeout}`);
    record('session name', infoData.guards.application_name === APP_NAME, `application_name=${infoData.guards.application_name}`);
    record('schemas reachable', infoData.schemas.every((/** @type {any} */ s) => s.exists && s.usage), infoData.schemas.map((/** @type {any} */ s) => `${s.schema}:${s.exists ? (s.usage ? 'ok' : 'no usage') : 'missing'}`).join(' '));
    record('connection_info <= 3 queries', info.catalog_queries <= MAX_QUERIES_PER_CALL, `${info.catalog_queries}`);
    for (const w of infoData.warnings) console.error(`  warning      ${w}`);

    // ---- A6 schema_overview ------------------------------------------------------------------
    const ovCold = await timed('schema_overview cold', 'schema_overview', { refresh: true });
    record('schema_overview works', !ovCold.isError, ovCold.isError ? ovCold.text.split('\n')[0] : 'ok');
    record('schema_overview <= 3 queries', ovCold.catalog_queries <= MAX_QUERIES_PER_CALL, `${ovCold.catalog_queries}`);
    record('schema_overview default under 25 KB', ovCold.bytes < OVERVIEW_BUDGET, `${ovCold.bytes} bytes`);
    const ovWarm = await timed('schema_overview warm', 'schema_overview', {});
    record('schema_overview warm = 0 queries', ovWarm.catalog_queries === 0, `${ovWarm.catalog_queries}`);
    const ovJson = await timed('schema_overview json', 'schema_overview', { format: 'json', limit: 1000, include_partitions: true });
    const ovData = JSON.parse(ovJson.text);
    record('relation count matches a direct catalog count', ovData.total_in_scope === directCount, `tool ${ovData.total_in_scope} vs direct ${directCount}`);
    const mvJson = await timed('schema_overview matviews', 'schema_overview', { format: 'json', kinds: ['matview'], limit: 1000 });
    const tracker = pickTrackerMatview(JSON.parse(mvJson.text).relations);

    // ---- A7 describe_table -------------------------------------------------------------------
    const tables = ['portal.freight_unit_enrich', 'portal."PurchaseOrderLine"', 'public.sql_source', ...(tracker ? [tracker] : [])];
    const dCold = await timed('describe_table cold', 'describe_table', { tables, refresh: true });
    record('describe_table works', !dCold.isError, dCold.isError ? dCold.text.split('\n')[0] : tables.join(', '));
    record('describe_table <= 3 queries', dCold.catalog_queries <= MAX_QUERIES_PER_CALL, `${dCold.catalog_queries}`);
    record('all reference tables resolve', new RegExp(`${tables.length} of ${tables.length} resolved`).test(dCold.text), dCold.text.split('\n')[0]);
    record('quoted mixed-case name resolves exactly', /## portal\."PurchaseOrderLine" · /.test(dCold.text) && !/matched case-insensitively/.test(dCold.text), 'portal."PurchaseOrderLine"');
    record('tracker materialized view found', Boolean(tracker), tracker ?? 'no materialized view in scope');
    const dWarm = await timed('describe_table warm', 'describe_table', { tables });
    record('describe_table warm = 0 queries', dWarm.catalog_queries === 0, `${dWarm.catalog_queries}`);

    // ---- idle close --------------------------------------------------------------------------
    const waitMs = config.idleMs + 5_000;
    console.error(`  waiting      ${Math.round(waitMs / 1000)} s for the server's idle sessions to close ...`);
    await new Promise((resolve) => setTimeout(resolve, waitMs));
    const activity = await readActivity();
    record('no mcp-pg-sqldev session after idle', Number(activity._mcp_sessions) === 0, `${activity._mcp_sessions} open (${Math.round(waitMs / 1000)} s after the last call)`);

    // ---- scan counters -----------------------------------------------------------------------
    // Read last: a backend flushes its statistics when it goes idle or exits, and ours have exited.
    const moved = diffCounters(countersBefore, await readCounters());
    const others = Number(activity._other_sessions);
    const verdict = counterVerdict(moved, others);
    record('scan counters did not move', verdict.status === 'PASS' ? true : verdict.status === 'INCONCLUSIVE' ? 'INCONCLUSIVE' : false, verdict.detail);
    for (const m of moved.slice(0, 10)) console.error(`               ${m.relation}: seq_scan +${m.seq_scan}, idx_scan +${m.idx_scan}${m.note ? ` (${m.note})` : ''}`);

    const failed = checks.filter((c) => c.status === 'FAIL').length;
    const inconclusive = checks.filter((c) => c.status === 'INCONCLUSIVE').length;
    const report = { ran_at: new Date().toISOString(), target: `${config.database}@${config.host}:${config.port}`, role: config.user, checks, calls, moved_counters: moved, other_sessions: others };
    fs.mkdirSync(config.cacheDir, { recursive: true });
    const file = path.join(config.cacheDir, 'smoke-report.json');
    fs.writeFileSync(file, JSON.stringify(report, null, 2));
    console.log(`\nsmoke: ${checks.length - failed - inconclusive} pass, ${failed} fail, ${inconclusive} inconclusive · report: ${file}`);
    exitCode = failed ? 1 : 0;
} catch (e) {
    console.error(`smoke aborted: ${explainDbError(e)}`);
    exitCode = 1;
} finally {
    try {
        await client?.close();
    } catch {
        /* server already gone */
    }
    await observer.end();
}
process.exit(exitCode);
