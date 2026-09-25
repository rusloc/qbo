// @ts-check
/**
 * Database access for pg-sqldev: a tiny pool, guards on every call, and honest accounting.
 *
 * Guard model
 * -----------
 * There is no raw query path. Every call goes through `readOnly(fn)`, which opens
 *
 *     begin transaction read only;
 *     set local statement_timeout = ...;
 *     set local lock_timeout = ...;
 *     set local idle_in_transaction_session_timeout = ...;
 *
 * runs the queries, and always ends with `rollback`.
 *
 * The guards are SET LOCAL inside the transaction, never session-level SET. Two reasons:
 *   1. Through a transaction-pooling PgBouncer (port 6432 on Azure) a session-level SET sticks to
 *      a server connection that is then handed to OTHER applications. A session-level
 *      default_transaction_read_only = on could make someone else's writes fail.
 *   2. A session default can be flipped from inside a statement with set_config(). An explicit
 *      read-only transaction cannot be made read-write once its first query has run.
 *
 * Statements supplied from outside (increment 2: explain_query, run_query) additionally pass the
 * classifier and are sent with the extended protocol, which refuses multi-statement strings at the
 * wire level.
 */
import { APP_NAME } from './config.js';
import { classify } from './classify.js';

/**
 * @typedef {{ query: (q: string | { text: string, values?: unknown[], queryMode?: string }) => Promise<{ rows: any[] }>, release: (err?: Error | boolean) => void,
 *   on?: (event: 'error', listener: (e: Error) => void) => unknown, off?: (event: 'error', listener: (e: Error) => void) => unknown }} DriverClient
 * @typedef {{ connect: () => Promise<DriverClient>, end: () => Promise<void> }} Driver
 * @typedef {{ query: (label: string, text: string, values?: unknown[]) => Promise<any[]>, guardedUserQuery: (label: string, text: string, opts?: { allowAnalyze?: boolean }) => Promise<any[]> }} Tx
 */

/**
 * @param {import('./config.js').Config} config
 * @param {{ driver?: Driver, applicationName?: string }} [opts] inject a driver for tests; default is a lazily created pg pool.
 *   `applicationName` lets the smoke test observe with a session name of its own.
 */
export function createDb(config, opts = {}) {
    /** @type {Driver | null} */
    let driver = opts.driver ?? null;

    const stats = {
        /** queries issued by tools: the number the acceptance checks count */
        catalogQueries: 0,
        /** every round trip including begin / set local / rollback */
        roundTrips: 0,
        transactions: 0,
        connectionsOpened: 0,
        errors: 0,
        /** @type {string | null} */
        lastQueryAt: null,
        /** @type {{ at: string, label: string, ms: number, rows: number }[]} */
        recent: [],
    };

    const guardSql = [
        'begin transaction read only',
        `set local statement_timeout = ${Number(config.statementTimeoutMs)}`,
        `set local lock_timeout = ${Number(config.lockTimeoutMs)}`,
        `set local idle_in_transaction_session_timeout = ${Number(config.statementTimeoutMs) + 15_000}`,
    ].join('; ');

    async function getDriver() {
        if (driver) return driver;
        if (!config.ready) throw new NotConfiguredError();
        const { default: pg } = await import('pg');
        const pool = new pg.Pool({
            host: config.host,
            port: config.port,
            database: config.database,
            user: config.user,
            password: config.password,
            ssl: config.ssl,
            application_name: opts.applicationName ?? APP_NAME,
            max: config.poolMax,
            min: 0,
            idleTimeoutMillis: config.idleMs,
            connectionTimeoutMillis: 10_000,
            // Client-side backstop in case the server-side statement_timeout cannot fire (network stall).
            query_timeout: config.statementTimeoutMs + 5_000,
            keepAlive: true,
            allowExitOnIdle: true,
        });
        pool.on('connect', () => {
            stats.connectionsOpened += 1;
        });
        // An idle client that errors (server restart, network drop) must not crash the process.
        pool.on('error', (err) => {
            console.error(`[pg-sqldev] idle connection error: ${safeMessage(err)}`);
        });
        driver = { connect: () => pool.connect(), end: () => pool.end() };
        return driver;
    }

    /**
     * Run `fn` inside a guarded read-only transaction. Always rolls back.
     * @template T
     * @param {(tx: Tx) => Promise<T>} fn
     * @returns {Promise<T>}
     */
    async function readOnly(fn) {
        const d = await getDriver();
        const client = await d.connect();
        /** @type {Error | undefined} */
        let fatal;
        // A connection that drops BETWEEN two queries raises an 'error' event on the client instead of
        // rejecting a query. Without a listener Node treats that as an uncaught exception and the
        // whole server dies. Catch it, and make sure the broken client never returns to the pool.
        const onClientError = (/** @type {Error} */ e) => {
            fatal = e;
            console.error(`[pg-sqldev] connection error during a call: ${safeMessage(e)}`);
        };
        client.on?.('error', onClientError);
        try {
            await client.query(guardSql);
            stats.roundTrips += 1;
            stats.transactions += 1;

            /** @type {Tx} */
            const tx = {
                async query(label, text, values = []) {
                    const started = Date.now();
                    stats.catalogQueries += 1;
                    stats.roundTrips += 1;
                    const res = await client.query({ text, values });
                    record(label, started, res.rows.length);
                    return res.rows;
                },
                async guardedUserQuery(label, text, o = {}) {
                    const verdict = classify(text, o);
                    if (!verdict.ok) throw new RefusedError(verdict.reason);
                    const started = Date.now();
                    stats.catalogQueries += 1;
                    stats.roundTrips += 1;
                    const res = await client.query({ text: verdict.statement, values: [], queryMode: 'extended' });
                    record(label, started, res.rows.length);
                    return res.rows;
                },
            };
            return await fn(tx);
        } catch (e) {
            stats.errors += 1;
            throw e;
        } finally {
            try {
                await client.query('rollback');
                stats.roundTrips += 1;
            } catch (e) {
                // A connection that cannot roll back is not returned to the pool.
                fatal = fatal ?? /** @type {Error} */ (e);
            }
            client.off?.('error', onClientError);
            client.release(fatal);
        }
    }

    /**
     * @param {string} label
     * @param {number} started
     * @param {number} rows
     */
    function record(label, started, rows) {
        const at = new Date().toISOString();
        stats.lastQueryAt = at;
        stats.recent.push({ at, label, ms: Date.now() - started, rows });
        if (stats.recent.length > 50) stats.recent.shift();
    }

    async function end() {
        if (driver) {
            const d = driver;
            driver = null;
            await d.end();
        }
    }

    return { readOnly, end, stats, guardSql, /** true when a test driver was injected */ injected: Boolean(opts.driver) };
}

/** @typedef {ReturnType<typeof createDb>} Db */

export class NotConfiguredError extends Error {
    constructor() {
        super('pg-sqldev is not configured');
        this.name = 'NotConfiguredError';
    }
}

export class RefusedError extends Error {
    /** @param {string} reason */
    constructor(reason) {
        super(`statement refused: ${reason}`);
        this.name = 'RefusedError';
    }
}

/**
 * Error text that is safe to show: message only, never the connection parameters.
 * @param {unknown} err
 */
export function safeMessage(err) {
    if (!err || typeof err !== 'object') return String(err);
    const e = /** @type {{ message?: string, code?: string }} */ (err);
    return `${e.message ?? 'unknown error'}${e.code ? ` [${e.code}]` : ''}`;
}

/**
 * Turn a driver / server error into a short explanation with a next step.
 * @param {unknown} err
 */
export function explainDbError(err) {
    const e = /** @type {{ message?: string, code?: string }} */ (err ?? {});
    const code = e.code ?? '';
    const msg = e.message ?? String(err);
    /** @type {Record<string, string>} */
    const hints = {
        '28P01': 'Authentication failed. Check PGUSER / PGPASSWORD in .env.',
        '28000': 'Connection rejected for this role or address. On Azure, check the cluster firewall rules for this machine’s public IP.',
        '3D000': 'Database does not exist. Check PGDATABASE in .env.',
        '42501': 'The role lacks a privilege for this object. Grant usage on the schema and select on its tables to the read-only role.',
        '57014': 'Statement timeout reached (PG_STATEMENT_TIMEOUT_MS). Nothing is left running on the server.',
        '55P03': 'Lock timeout reached (PG_LOCK_TIMEOUT_MS): another session holds a conflicting lock, for example a materialized view refresh. Retry shortly.',
        '25006': 'The statement tried to write inside the read-only transaction and was stopped.',
        '53300': 'The server has no free connection slots. Retry later.',
        ENOTFOUND: 'Host not found. Check PGHOST in .env and the network / VPN.',
        ETIMEDOUT: 'Connection timed out. On Azure this is usually the cluster firewall: allow this machine’s public IP.',
        ECONNREFUSED: 'Connection refused. Check PGHOST / PGPORT.',
        ECONNRESET: 'Connection reset by the server or the network. Retry.',
        SELF_SIGNED_CERT_IN_CHAIN: 'TLS verification failed. Set PGSSLROOTCERT in .env to the CA bundle Azure documents for this service. Verification is never switched off.',
        UNABLE_TO_GET_ISSUER_CERT_LOCALLY: 'TLS verification failed: issuer not in the trust store. Set PGSSLROOTCERT in .env to the Azure CA bundle.',
        DEPTH_ZERO_SELF_SIGNED_CERT: 'TLS verification failed: self-signed server certificate. Set PGSSLROOTCERT only if this is expected.',
    };
    let hint = hints[code];
    if (!hint && /timeout exceeded when trying to connect|Connection terminated due to connection timeout/i.test(msg)) hint = hints.ETIMEDOUT;
    if (!hint && /Query read timeout/i.test(msg)) hint = 'Client-side query timeout reached. The server-side statement_timeout should have fired first; check the network.';
    return `${safeMessage(err)}${hint ? `\nHint: ${hint}` : ''}`;
}
