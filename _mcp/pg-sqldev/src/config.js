// @ts-check
/**
 * Configuration for pg-sqldev.
 *
 * The connection secret lives in `.env` beside package.json. This module is the only reader.
 * Values are parsed into a plain object and are never copied into process.env, never logged,
 * and never returned by a tool. `describeConfig()` is the redacted view that tools may show.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { parseEnv } from 'node:util';

export const SERVER_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const APP_NAME = 'mcp-pg-sqldev';

const REQUIRED = ['PGHOST', 'PGDATABASE', 'PGUSER', 'PGPASSWORD'];
const KNOWN = [
    ...REQUIRED,
    'PGPORT',
    'PG_SCHEMAS',
    'PG_STATEMENT_TIMEOUT_MS',
    'PG_LOCK_TIMEOUT_MS',
    'PG_CACHE_TTL_S',
    'PG_POOL_MAX',
    'PG_IDLE_MS',
    'PGSSLROOTCERT',
];

/**
 * @param {string | undefined} raw
 * @param {number} fallback
 * @param {number} min
 * @param {number} max
 */
function intInRange(raw, fallback, min, max) {
    if (raw === undefined || raw === '') return fallback;
    const n = Number(raw);
    if (!Number.isInteger(n)) return fallback;
    return Math.min(max, Math.max(min, n));
}

/**
 * Load and validate configuration. Never throws: problems are reported in `missing` / `errors`
 * so the server can still start and explain itself through a tool result.
 *
 * Precedence: the `.env` file wins, process environment only fills gaps. The file is the single
 * documented place for settings, so a stray machine-level PG* variable cannot silently redirect
 * the server to another database.
 *
 * @param {{ envFile?: string, env?: Record<string, string | undefined> }} [opts]
 */
export function loadConfig(opts = {}) {
    const env = opts.env ?? process.env;
    const envFile = opts.envFile ?? env.PG_SQLDEV_ENV_FILE ?? path.join(SERVER_DIR, '.env');

    /** @type {Record<string, string | undefined>} */
    let fileVals = {};
    let envFileFound = false;
    /** @type {string[]} */
    const errors = [];
    try {
        fileVals = parseEnv(fs.readFileSync(envFile, 'utf8'));
        envFileFound = true;
    } catch (e) {
        if (/** @type {NodeJS.ErrnoException} */ (e).code !== 'ENOENT') {
            errors.push(`cannot read env file: ${/** @type {Error} */ (e).message}`);
        }
    }

    /** @type {Record<string, string | undefined>} */
    const v = {};
    /** @type {Record<string, 'file' | 'env' | 'default'>} */
    const source = {};
    for (const k of KNOWN) {
        const fromFile = fileVals[k];
        const fromEnv = env[k];
        if (fromFile !== undefined && fromFile !== '') {
            v[k] = fromFile;
            source[k] = 'file';
        } else if (fromEnv !== undefined && fromEnv !== '') {
            v[k] = fromEnv;
            source[k] = 'env';
        } else {
            source[k] = 'default';
        }
    }

    const missing = REQUIRED.filter((k) => !v[k]);

    const schemas = (v.PG_SCHEMAS ?? 'public,portal,portal_dev')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    if (schemas.length === 0) errors.push('PG_SCHEMAS is empty');

    // TLS: verification is always on. There is deliberately no switch to turn it off.
    /** @type {{ rejectUnauthorized: true, ca?: string }} */
    const ssl = { rejectUnauthorized: true };
    if (v.PGSSLROOTCERT) {
        try {
            ssl.ca = fs.readFileSync(v.PGSSLROOTCERT, 'utf8');
        } catch (e) {
            errors.push(`PGSSLROOTCERT is set but unreadable: ${/** @type {Error} */ (e).message}`);
        }
    }

    const host = v.PGHOST ?? '';
    const port = intInRange(v.PGPORT, 5432, 1, 65535);
    const database = v.PGDATABASE ?? '';
    const user = v.PGUSER ?? '';

    const config = {
        envFile,
        envFileFound,
        missing,
        errors,
        ready: missing.length === 0 && errors.length === 0,
        source,
        host,
        port,
        database,
        user,
        password: v.PGPASSWORD ?? '',
        ssl,
        customCa: Boolean(ssl.ca),
        schemas,
        statementTimeoutMs: intInRange(v.PG_STATEMENT_TIMEOUT_MS, 15_000, 1_000, 120_000),
        lockTimeoutMs: intInRange(v.PG_LOCK_TIMEOUT_MS, 2_000, 100, 30_000),
        cacheTtlMs: intInRange(v.PG_CACHE_TTL_S, 600, 0, 86_400) * 1000,
        // Two connections at most, by design. The setting can only lower it.
        poolMax: intInRange(v.PG_POOL_MAX, 2, 1, 2),
        // Idle sessions close after 25 s, so "no session 30 s after the last call" holds with margin.
        idleMs: intInRange(v.PG_IDLE_MS, 25_000, 1_000, 30_000),
        cacheDir: path.join(SERVER_DIR, '.cache'),
        // Fingerprint of the connection target. Keys the cache snapshot; holds no secret.
        identity: crypto
            .createHash('sha256')
            .update([host, port, database, user].join('|'))
            .digest('hex')
            .slice(0, 12),
    };
    // Keep the password out of accidental JSON.stringify / console output of the whole object.
    Object.defineProperty(config, 'password', { enumerable: false });
    return config;
}

/** @typedef {ReturnType<typeof loadConfig>} Config */

/**
 * Redacted, display-safe view of the configuration.
 * @param {Config} config
 */
export function describeConfig(config) {
    return {
        env_file: config.envFile,
        env_file_found: config.envFileFound,
        ready: config.ready,
        missing: config.missing,
        errors: config.errors,
        host: config.host,
        port: config.port,
        database: config.database,
        user: config.user,
        password: config.password ? '(set)' : '(not set)',
        tls: config.customCa ? 'verify, custom CA bundle' : 'verify, Node default CA store',
        schemas: config.schemas,
        statement_timeout_ms: config.statementTimeoutMs,
        lock_timeout_ms: config.lockTimeoutMs,
        cache_ttl_s: config.cacheTtlMs / 1000,
        pool_max: config.poolMax,
        idle_close_ms: config.idleMs,
    };
}

/**
 * The message every DB tool returns while the server is not configured.
 * @param {Config} config
 */
export function notReadyMessage(config) {
    const lines = ['pg-sqldev is not configured, so no database call was made.'];
    if (!config.envFileFound) {
        lines.push(`No env file at: ${config.envFile}`);
        lines.push('Create it by copying .env.example (same folder) to .env and filling in the blanks.');
    }
    if (config.missing.length) lines.push(`Missing settings: ${config.missing.join(', ')}`);
    for (const e of config.errors) lines.push(`Config error: ${e}`);
    lines.push('Restart the MCP server after editing .env (it is read once at startup).');
    return lines.join('\n');
}
