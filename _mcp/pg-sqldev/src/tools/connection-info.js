// @ts-check
import { z } from 'zod';
import { describeConfig } from '../config.js';
import { getCapabilities } from '../capabilities.js';
import { cacheLabel } from '../cache.js';
import { loadSql } from '../sql.js';
import { safeMessage } from '../db.js';

/** @typedef {import('../capabilities.js').Ctx} Ctx */

export const connectionInfo = {
    name: 'connection_info',
    title: 'Connection info',
    description:
        'Server version, Citus yes/no, current role, the read-only guards actually in force, schemas in scope, cache and query counters. ' +
        'Call once at the start of a session. Cost: one catalog query, cached (a second small one on a Citus cluster). Never touches user tables.',
    input: {
        refresh: z.boolean().optional().describe('Bypass the cache and re-read from the server.'),
        format: z.enum(['text', 'json']).optional().describe('Default "text".'),
    },

    /**
     * @param {Ctx} ctx
     * @param {{ refresh?: boolean, format?: 'text' | 'json' }} args
     */
    async handler(ctx, args) {
        const caps = await getCapabilities(ctx, { refresh: args.refresh });
        const c = caps.value;

        /** @type {{ value: Record<string, number> | null, note: string | null }} */
        let citus = { value: null, note: null };
        if (c.citus) {
            try {
                const r = await ctx.cache.getOrLoad(
                    'citus-summary',
                    async () => (await ctx.db.readOnly((tx) => tx.query('citus-summary', loadSql('citus-summary'))))[0],
                    { refresh: args.refresh },
                );
                citus.value = {
                    distributed: Number(r.value._distributed_tables),
                    append_range: Number(r.value._append_range_tables),
                    reference: Number(r.value._reference_tables),
                    local_managed: Number(r.value._local_managed_tables),
                };
            } catch (e) {
                citus.note = `Citus table counts unavailable: ${safeMessage(e)}`;
            }
        }

        /** @type {string[]} */
        const warnings = [];
        if (c.transaction_read_only !== 'on') {
            warnings.push('GUARD FAILURE: the transaction is not read-only. Stop and report this.');
        }
        if (c.is_superuser) {
            warnings.push('The role is a superuser. Read-only is enforced per transaction only. A dedicated read-only role is the stronger barrier (decision D1).');
        }
        if (c.is_replica) warnings.push('Connected to a replica (hot standby). Statistics views reflect the replica.');
        for (const s of c.schemas) {
            if (!s.exists) warnings.push(`Schema "${s.schema}" does not exist in this database (check PG_SCHEMAS).`);
            else if (!s.usage) warnings.push(`No USAGE privilege on schema "${s.schema}": its tables will be invisible to the tools.`);
        }
        if (c.citus_version && !c.citus_metadata_readable) {
            warnings.push('Citus is installed but pg_dist_partition is not readable for this role: distributed tables cannot be flagged.');
        }
        if (citus.note) warnings.push(citus.note);
        if (citus.value && citus.value.distributed + citus.value.append_range + citus.value.reference > 0) {
            warnings.push(
                'Distributed / reference tables exist. For those, row estimates, sizes and column statistics on the coordinator are empty and are shown as "?".',
            );
        }

        const cfg = describeConfig(ctx.config);
        const s = ctx.db.stats;
        const data = {
            server: { name: 'pg-sqldev', version: ctx.version },
            postgres: { version: c.server_version, version_num: c.server_version_num, replica: c.is_replica, timezone: c.timezone, encoding: c.encoding },
            target: { host: cfg.host, port: cfg.port, database: c.database, tls: cfg.tls },
            role: { current: c.current_role, session: c.session_role, superuser: c.is_superuser },
            citus: { version: c.citus_version, metadata_readable: c.citus_metadata_readable, tables: citus.value },
            pg_stat_statements: c.pg_stat_statements_version,
            guards: {
                transaction_read_only: c.transaction_read_only,
                statement_timeout: c.statement_timeout,
                lock_timeout: c.lock_timeout,
                application_name: c.application_name,
                session_default_read_only: c.default_read_only,
                model: 'per transaction (begin read only + set local), never session-level',
            },
            schemas: c.schemas,
            limits: { max_connections: c.max_connections, pool_max: cfg.pool_max, idle_close_ms: cfg.idle_close_ms },
            cache: ctx.cache.info(),
            process: {
                catalog_queries: s.catalogQueries,
                round_trips: s.roundTrips,
                transactions: s.transactions,
                connections_opened: s.connectionsOpened,
                errors: s.errors,
                last_query_at: s.lastQueryAt,
            },
            source: cacheLabel(caps),
            warnings,
        };
        if (args.format === 'json') return JSON.stringify(data, null, 1);

        const ci = data.cache;
        const citusLine = !c.citus_version
            ? 'not installed'
            : citus.value
              ? `${c.citus_version} · distributed ${citus.value.distributed} · append/range ${citus.value.append_range} · reference ${citus.value.reference} · local ${citus.value.local_managed}`
              : `${c.citus_version} · table counts unavailable`;
        const lines = [
            `pg-sqldev ${ctx.version} · connection_info · ${data.source}`,
            '',
            `postgres    ${c.server_version} (${c.server_version_num})${c.is_replica ? ' · replica' : ''} · tz ${c.timezone} · ${c.encoding}`,
            `target      ${c.database} @ ${cfg.host}:${cfg.port} · TLS ${cfg.tls}`,
            `role        ${c.current_role}${c.session_role !== c.current_role ? ` (session ${c.session_role})` : ''} · superuser ${c.is_superuser ? 'YES' : 'no'}`,
            `citus       ${citusLine}`,
            `pg_stat_statements  ${c.pg_stat_statements_version ?? 'not installed'}`,
            `guards      transaction_read_only=${c.transaction_read_only} · statement_timeout=${c.statement_timeout} · lock_timeout=${c.lock_timeout} · app=${c.application_name}`,
            `            applied per transaction with SET LOCAL (session default_transaction_read_only=${c.default_read_only} is untouched by design)`,
            `schemas     ${c.schemas.map((x) => `${x.schema} (${!x.exists ? 'MISSING' : x.usage ? 'ok' : 'NO USAGE'})`).join(' · ')}`,
            `limits      server max_connections ${c.max_connections} · pool max ${cfg.pool_max} · idle close ${cfg.idle_close_ms / 1000} s`,
            `cache       ${ci.enabled ? `ttl ${ci.ttl_s} s` : 'disabled'} · ${ci.entries} entries · hits ${ci.hits} · loads ${ci.loads} · from snapshot ${ci.snapshotLoaded}`,
            `process     catalog queries ${s.catalogQueries} · round trips ${s.roundTrips} · transactions ${s.transactions} · connections opened ${s.connectionsOpened} · errors ${s.errors}`,
        ];
        if (warnings.length) lines.push('', 'warnings', ...warnings.map((w) => `  - ${w}`));
        return lines.join('\n');
    },
};
