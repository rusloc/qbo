#!/usr/bin/env node
// @ts-check
/**
 * Increment 0: the probe (build step A1).
 *
 * Run once with your credentials:   node scripts/probe.js
 * Writes .cache/probe.json and prints a summary that can be pasted into the coms log.
 *
 * At most nine catalog queries, each in its own guarded read-only transaction, so one missing
 * privilege cannot abort the rest. No user table is read: public.sql_source is described from the
 * catalog, its rows are not touched. Nothing secret is printed or written.
 */
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { loadConfig, notReadyMessage, APP_NAME } from '../src/config.js';
import { createDb, explainDbError, safeMessage } from '../src/db.js';
import { createCache } from '../src/cache.js';
import { getCapabilities } from '../src/capabilities.js';
import { loadSql } from '../src/sql.js';
import { loadRelations } from '../src/tools/schema-overview.js';
import { fetchBatch } from '../src/tools/describe-table.js';
import { fmtCount, fmtBytes } from '../src/format.js';

/**
 * @template T
 * @param {() => Promise<T>} fn
 * @returns {Promise<{ ok: true, data: T } | { ok: false, error: string }>}
 */
async function step(fn) {
    try {
        return { ok: true, data: await fn() };
    } catch (e) {
        return { ok: false, error: safeMessage(e) };
    }
}

/**
 * @param {import('../src/capabilities.js').Ctx} ctx
 */
export async function runProbe(ctx) {
    const started = Date.now();
    const { config, db } = ctx;

    // 1. Server, role, guards, extensions, schemas. Everything else branches on this, so it may throw.
    const caps = (await getCapabilities(ctx, { refresh: true })).value;

    // 2. Privileges and statistics coverage per schema and kind.
    const coverage = await step(() => db.readOnly((tx) => tx.query('probe-coverage', loadSql('probe-coverage'), [config.schemas])));

    // 3. The relation list: exercises the schema_overview query on the real catalog.
    const overview = await step(async () => (await loadRelations(ctx, { refresh: true })).value);

    // 4. Shape of public.sql_source, from the catalog only: exercises both describe_table queries.
    const sqlSource = await step(async () => {
        const batch = await fetchBatch(ctx, [{ key: 'probe:sql_source', schema: 'public', name: 'sql_source' }], false, false);
        return batch.get('probe:sql_source')?.[0] ?? null;
    });

    // 5. Connection headroom.
    const activity = await step(async () => (await db.readOnly((tx) => tx.query('probe-activity', loadSql('probe-activity'), [APP_NAME])))[0]);

    // 6. pg_stat_statements, only when the extension is installed.
    const pgss = caps.pg_stat_statements_version
        ? await step(async () => (await db.readOnly((tx) => tx.query('probe-pgss', loadSql('probe-pgss'))))[0])
        : null;

    // 7 + 8. Citus, only when installed and readable.
    const citusTables = caps.citus ? await step(async () => (await db.readOnly((tx) => tx.query('citus-summary', loadSql('citus-summary'))))[0]) : null;
    const citusNodes = caps.citus ? await step(async () => (await db.readOnly((tx) => tx.query('probe-citus-nodes', loadSql('probe-citus-nodes'))))[0]) : null;

    // ---- derive the decisions the plan waits for -------------------------------------------
    const cov = coverage.ok ? coverage.data : [];
    const storage = cov.filter((r) => ['r', 'm', 'p'].includes(r._kind));
    const sum = (/** @type {any[]} */ rows, /** @type {string} */ k) => rows.reduce((a, r) => a + Number(r[k] ?? 0), 0);
    const relationsTotal = sum(cov, '_relations');
    const selectableTotal = sum(cov, '_selectable');
    const storageTotal = sum(storage, '_relations');
    const withStats = sum(storage, '_with_column_stats');
    const neverAnalyzed = sum(storage, '_never_analyzed');
    const nonEmpty = sum(storage, '_nonempty');
    const nonEmptyWithoutStats = sum(storage, '_nonempty_without_stats');
    // Share of non-empty tables that do have column statistics. Empty tables never have any.
    const statsShare = nonEmpty ? (nonEmpty - nonEmptyWithoutStats) / nonEmpty : null;

    const distributed = citusTables?.ok ? Number(citusTables.data._distributed_tables) + Number(citusTables.data._append_range_tables) : 0;
    const reference = citusTables?.ok ? Number(citusTables.data._reference_tables) : 0;

    const relations = overview.ok ? overview.data.relations : [];
    const largest = [...relations]
        .filter((r) => r.est_bytes)
        .sort((a, b) => (b.est_bytes ?? 0) - (a.est_bytes ?? 0))
        .slice(0, 12)
        .map((r) => ({ relation: `${r.schema}.${r.name}`, kind: r.kind, est_rows: r.est_rows, est_bytes: r.est_bytes, last_analyze: r.last_analyze }));
    const matviews = relations.filter((r) => r.kind === 'm').map((r) => `${r.schema}.${r.name}`);

    const expectedCols = ['_report', '_page', '_code', '_updated'];
    const sqlSourceCols = sqlSource.ok && sqlSource.data ? sqlSource.data.columns.map((/** @type {any} */ c) => c.column) : [];

    /** @type {string[]} */
    const findings = [];
    if (caps.transaction_read_only !== 'on') findings.push('GUARD FAILURE: the probe transaction was not read-only.');
    if (caps.is_superuser) findings.push('The role is a superuser: create the dedicated read-only role (D1) before daily use.');
    for (const s of caps.schemas) {
        if (!s.exists) findings.push(`Schema "${s.schema}" does not exist: fix PG_SCHEMAS.`);
        else if (!s.usage) findings.push(`No USAGE on schema "${s.schema}": grant it to the role.`);
    }
    if (relationsTotal && selectableTotal < relationsTotal) {
        findings.push(`${relationsTotal - selectableTotal} of ${relationsTotal} relations are not selectable: their column statistics are invisible to describe_table.`);
    }
    if (distributed + reference > 0) {
        findings.push(`Citus: ${distributed} distributed and ${reference} reference tables. Coordinator rows / sizes / column statistics are empty for them: column_profile (C1) should move forward.`);
    } else if (caps.citus_version) {
        findings.push('Citus is installed but no table is distributed: the plain catalog path is exact, the Citus branch stays dormant.');
    }
    if (statsShare !== null && statsShare < 0.8) {
        findings.push(`Only ${Math.round(statsShare * 100)}% of non-empty tables / matviews have column statistics (${nonEmptyWithoutStats} of ${nonEmpty} lack them, ${neverAnalyzed} never analyzed): column_profile (C1) should move forward.`);
    }
    if (pgss === null) findings.push('pg_stat_statements is not installed: drop top_queries (C4).');
    else if (!pgss.ok) findings.push(`pg_stat_statements is installed but not readable (${pgss.error}): drop top_queries (C4) or grant pg_read_all_stats.`);
    else if (Number(pgss.data._hidden_text) > 0) {
        findings.push(`pg_stat_statements hides the text of ${pgss.data._hidden_text} of ${pgss.data._statements} statements from this role: top_queries (C4) needs pg_read_all_stats.`);
    }
    if (sqlSource.ok && !sqlSource.data) findings.push('public.sql_source was not found or is not visible: the sql_source tool (B5) has no contract yet.');
    else if (sqlSource.ok) {
        const lacking = expectedCols.filter((c) => !sqlSourceCols.includes(c));
        if (lacking.length) findings.push(`public.sql_source lacks expected columns: ${lacking.join(', ')}.`);
        if (!sqlSource.data.can_select) findings.push('public.sql_source is not selectable for this role: the sql_source tool (B5) will not work.');
    }
    if (relations.length > 1000) findings.push(`${relations.length} relations in scope: keep the schema_overview default limit at 100 and rely on pattern / family filters.`);
    if (activity.ok && caps.max_connections && Number(activity.data._sessions) / caps.max_connections > 0.8) {
        findings.push(`Connection pressure: ${activity.data._sessions} of ${caps.max_connections} slots in use. Consider PG_POOL_MAX=1.`);
    }

    return {
        probed_at: new Date().toISOString(),
        duration_ms: Date.now() - started,
        catalog_queries: db.stats.catalogQueries,
        target: { host: config.host, port: config.port, database: caps.database },
        server: { version: caps.server_version, version_num: caps.server_version_num, replica: caps.is_replica, timezone: caps.timezone, max_connections: caps.max_connections },
        role: { current: caps.current_role, superuser: caps.is_superuser },
        guards: { transaction_read_only: caps.transaction_read_only, statement_timeout: caps.statement_timeout, lock_timeout: caps.lock_timeout, application_name: caps.application_name },
        schemas: caps.schemas,
        citus: { version: caps.citus_version, metadata_readable: caps.citus_metadata_readable, tables: citusTables, nodes: citusNodes },
        pg_stat_statements: { version: caps.pg_stat_statements_version, readable: pgss },
        coverage,
        totals: { relations: relationsTotal, selectable: selectableTotal, tables_and_matviews: storageTotal, with_column_stats: withStats, non_empty: nonEmpty, non_empty_without_stats: nonEmptyWithoutStats, never_analyzed: neverAnalyzed },
        overview: overview.ok ? { relations: relations.length, note: overview.data.note, largest, matviews } : overview,
        sql_source: sqlSource.ok
            ? sqlSource.data && {
                  columns: sqlSource.data.columns.map((/** @type {any} */ c) => ({ column: c.column, type: c.type, not_null: c.not_null })),
                  constraints: sqlSource.data.constraints.map((/** @type {any} */ k) => k.definition),
                  est_rows: sqlSource.data.est_rows,
                  est_table_bytes: sqlSource.data.est_table_bytes,
                  can_select: sqlSource.data.can_select,
              }
            : sqlSource,
        activity,
        findings,
    };
}

/** @param {Awaited<ReturnType<typeof runProbe>>} r */
export function renderProbe(r) {
    const cov = r.coverage.ok ? r.coverage.data : [];
    const kind = /** @type {Record<string, string>} */ ({ r: 'tables', p: 'partitioned', v: 'views', m: 'matviews', f: 'foreign' });
    const lines = [
        `pg-sqldev probe · ${r.probed_at} · ${r.catalog_queries} catalog queries · ${r.duration_ms} ms · no user table read`,
        '',
        `- server: PostgreSQL ${r.server.version}${r.server.replica ? ' (replica)' : ''}, db ${r.target.database} @ ${r.target.host}:${r.target.port}, tz ${r.server.timezone}, max_connections ${r.server.max_connections}`,
        `- role: ${r.role.current}, superuser ${r.role.superuser ? 'YES' : 'no'}`,
        `- guards seen inside the transaction: read_only=${r.guards.transaction_read_only}, statement_timeout=${r.guards.statement_timeout}, lock_timeout=${r.guards.lock_timeout}, app=${r.guards.application_name}`,
        `- schemas: ${r.schemas.map((s) => `${s.schema} ${!s.exists ? 'MISSING' : s.usage ? 'ok' : 'NO USAGE'}`).join(', ')}`,
        `- citus: ${r.citus.version ?? 'not installed'}${r.citus.tables?.ok ? ` · distributed ${r.citus.tables.data._distributed_tables}, append/range ${r.citus.tables.data._append_range_tables}, reference ${r.citus.tables.data._reference_tables}, local ${r.citus.tables.data._local_managed_tables}` : ''}${r.citus.tables && !r.citus.tables.ok ? ` · table counts failed: ${r.citus.tables.error}` : ''}${r.citus.nodes?.ok ? ` · ${r.citus.nodes.data._active_nodes} active nodes, ${r.citus.nodes.data._shards} shards` : ''}${r.citus.nodes && !r.citus.nodes.ok ? ` · node metadata not readable: ${r.citus.nodes.error}` : ''}`,
        `- pg_stat_statements: ${r.pg_stat_statements.version ?? 'not installed'}${r.pg_stat_statements.readable?.ok ? ` · ${r.pg_stat_statements.readable.data._statements} statements, ${r.pg_stat_statements.readable.data._hidden_text} with hidden text` : ''}${r.pg_stat_statements.readable && !r.pg_stat_statements.readable.ok ? ` · not readable: ${r.pg_stat_statements.readable.error}` : ''}`,
        `- relations in scope: ${r.totals.relations}, selectable ${r.totals.selectable} · tables + matviews ${r.totals.tables_and_matviews}: non-empty ${r.totals.non_empty}, of those without column statistics ${r.totals.non_empty_without_stats}, never analyzed ${r.totals.never_analyzed}`,
    ];
    if (!r.coverage.ok) lines.push(`- coverage query FAILED: ${r.coverage.error}`);
    for (const c of cov) {
        lines.push(
            `  - ${c._schema} ${kind[c._kind] ?? c._kind}: ${c._relations} (selectable ${c._selectable}, with column stats ${c._with_column_stats}, never analyzed ${c._never_analyzed}, analyzed <7d ${c._analyzed_last_7d}, >30d ${c._analyzed_older_30d}, est rows ${fmtCount(Number(c._est_rows_total))}, largest ${fmtCount(Number(c._est_rows_largest))})`,
        );
    }
    if ('relations' in r.overview) {
        lines.push(`- largest relations: ${r.overview.largest.slice(0, 8).map((l) => `${l.relation} ${fmtBytes(l.est_bytes)} / ${fmtCount(l.est_rows)} rows`).join('; ') || 'none sized'}`);
        lines.push(`- materialized views: ${r.overview.matviews.join(', ') || 'none'}`);
        if (r.overview.note) lines.push(`- overview note: ${r.overview.note}`);
    } else lines.push(`- overview query FAILED: ${r.overview.error}`);
    if (r.sql_source && 'columns' in r.sql_source) {
        lines.push(
            `- public.sql_source: ${r.sql_source.columns.map((/** @type {any} */ c) => `${c.column} ${c.type}`).join(', ')} · keys: ${r.sql_source.constraints.join('; ') || 'none declared'} · est rows ${fmtCount(r.sql_source.est_rows)} · select ${r.sql_source.can_select ? 'yes' : 'NO'}`,
        );
    } else lines.push(`- public.sql_source: ${r.sql_source && 'error' in r.sql_source ? `FAILED: ${r.sql_source.error}` : 'not found / not visible'}`);
    if (r.activity.ok) {
        lines.push(`- sessions: ${r.activity.data._sessions} of ${r.server.max_connections} (active ${r.activity.data._active}, idle in transaction ${r.activity.data._idle_in_transaction}, ours ${r.activity.data._mcp_sessions})`);
    } else lines.push(`- session count FAILED: ${r.activity.error}`);
    lines.push('', r.findings.length ? 'findings that change the build:' : 'findings that change the build: none', ...r.findings.map((f) => `- ${f}`));
    return lines.join('\n');
}

// ---- CLI ---------------------------------------------------------------------------------------
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    const config = loadConfig();
    if (!config.ready) {
        console.error(notReadyMessage(config));
        process.exit(2);
    }
    const db = createDb(config);
    // In-memory cache only: the probe must always read the live catalog.
    const cache = createCache({ ttlMs: 60_000, identity: config.identity });
    try {
        const report = await runProbe({ config, db, cache, version: 'probe' });
        fs.mkdirSync(config.cacheDir, { recursive: true });
        const file = path.join(config.cacheDir, 'probe.json');
        fs.writeFileSync(file, JSON.stringify(report, null, 2));
        console.log(renderProbe(report));
        console.log(`\nfull result: ${file}`);
    } catch (e) {
        console.error(`probe failed: ${explainDbError(e)}`);
        process.exitCode = 1;
    } finally {
        await db.end();
    }
}
