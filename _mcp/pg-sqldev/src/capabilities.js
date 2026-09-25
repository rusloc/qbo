// @ts-check
/**
 * Server capabilities: one cached catalog query that every tool shares.
 * It answers the two questions the other tools branch on: is Citus here and readable, and are the
 * guards really in force.
 */
import { loadSql } from './sql.js';
import { safeMessage } from './db.js';

/**
 * @typedef {{ config: import('./config.js').Config, db: import('./db.js').Db, cache: import('./cache.js').Cache, version: string }} Ctx
 */

/**
 * @param {Ctx} ctx
 * @param {{ refresh?: boolean }} [o]
 */
export async function getCapabilities(ctx, o = {}) {
    return ctx.cache.getOrLoad(
        'capabilities',
        async () => {
            const rows = await ctx.db.readOnly((tx) => tx.query('connection-info', loadSql('connection-info'), [ctx.config.schemas]));
            const r = rows[0];
            return {
                server_version: /** @type {string} */ (r._server_version),
                server_version_num: Number(r._server_version_num),
                database: /** @type {string} */ (r._database),
                current_role: /** @type {string} */ (r._current_role),
                session_role: /** @type {string} */ (r._session_role),
                is_superuser: r._is_superuser === true,
                is_replica: r._is_replica === true,
                transaction_read_only: /** @type {string} */ (r._transaction_read_only),
                default_read_only: /** @type {string} */ (r._default_read_only),
                statement_timeout: /** @type {string} */ (r._statement_timeout),
                lock_timeout: /** @type {string} */ (r._lock_timeout),
                application_name: /** @type {string} */ (r._application_name),
                max_connections: Number(r._max_connections),
                timezone: /** @type {string} */ (r._timezone),
                encoding: /** @type {string} */ (r._encoding),
                citus_version: /** @type {string | null} */ (r._citus_version ?? null),
                citus_metadata_readable: r._citus_metadata_readable === true,
                // The Citus branch of a query is used only when the extension is there AND readable.
                citus: Boolean(r._citus_version) && r._citus_metadata_readable === true,
                pg_stat_statements_version: /** @type {string | null} */ (r._pg_stat_statements_version ?? null),
                schemas: /** @type {{ schema: string, exists: boolean, usage: boolean }[]} */ (r._schemas ?? []),
            };
        },
        o,
    );
}

/** Errors that mean "the Citus form of this query does not work here", not "the database is down". */
const CITUS_FALLBACK_CODES = new Set(['42501', '42P01', '42883', '42703', '42704']);

/**
 * Run the Citus form of a query when the cluster has readable Citus metadata, and fall back to the
 * plain form if that form is not usable for this role or version. Each attempt is its own
 * transaction, because a failed statement aborts the transaction it ran in.
 *
 * @template T
 * @param {boolean} citus
 * @param {(citus: boolean) => Promise<T>} run
 * @returns {Promise<{ result: T, citus: boolean, note: string | null }>}
 */
export async function withCitusFallback(citus, run) {
    if (citus) {
        try {
            return { result: await run(true), citus: true, note: null };
        } catch (e) {
            const code = /** @type {{ code?: string }} */ (e).code ?? '';
            if (!CITUS_FALLBACK_CODES.has(code)) throw e;
            const note = `Citus metadata query failed (${safeMessage(e)}). Fell back to the plain catalog query: distribution info is missing.`;
            return { result: await run(false), citus: false, note };
        }
    }
    return { result: await run(false), citus: false, note: null };
}
