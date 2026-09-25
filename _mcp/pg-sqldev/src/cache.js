// @ts-check
/**
 * TTL cache with a JSON snapshot on disk.
 *
 * - In memory: key -> { storedAt, value }. An entry older than the TTL is treated as absent.
 * - On disk: one JSON file, rewritten atomically after every set. A new server process starts
 *   warm from it, so opening the editor does not cost a catalog query.
 * - The snapshot carries the connection fingerprint. Pointing .env at another database makes the
 *   old snapshot unusable instead of serving the wrong catalog.
 * - Concurrent loads of the same key share one promise, so two parallel tool calls cost one query.
 * - A snapshot problem (read-only disk, corrupt file) never fails a tool call.
 *
 * Note: cached values include column statistics, and those include real data values (most common
 * values). The snapshot therefore lives in .cache/, which is ignored by git.
 */
import fs from 'node:fs';
import path from 'node:path';

const SNAPSHOT_VERSION = 1;
const MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024;

/**
 * @param {{ ttlMs: number, identity: string, snapshotFile?: string | null, now?: () => number }} opts
 */
export function createCache(opts) {
    const now = opts.now ?? Date.now;
    const ttlMs = opts.ttlMs;
    const snapshotFile = opts.snapshotFile ?? null;

    /** @type {Map<string, { storedAt: number, value: any }>} */
    const entries = new Map();
    /** @type {Map<string, Promise<any>>} */
    const inflight = new Map();
    const counters = { hits: 0, misses: 0, loads: 0, snapshotLoaded: 0, snapshotErrors: 0 };

    loadSnapshot();

    function loadSnapshot() {
        if (!snapshotFile || ttlMs <= 0) return;
        try {
            const snap = JSON.parse(fs.readFileSync(snapshotFile, 'utf8'));
            if (snap.version !== SNAPSHOT_VERSION || snap.identity !== opts.identity) return;
            for (const [key, entry] of Object.entries(snap.entries ?? {})) {
                const e = /** @type {{ storedAt: number, value: any }} */ (entry);
                if (typeof e.storedAt === 'number' && now() - e.storedAt < ttlMs) {
                    entries.set(key, e);
                    counters.snapshotLoaded += 1;
                }
            }
        } catch (e) {
            if (/** @type {NodeJS.ErrnoException} */ (e).code !== 'ENOENT') counters.snapshotErrors += 1;
        }
    }

    function saveSnapshot() {
        if (!snapshotFile || ttlMs <= 0) return;
        try {
            /** @type {Record<string, { storedAt: number, value: any }>} */
            const live = {};
            for (const [key, entry] of entries) if (now() - entry.storedAt < ttlMs) live[key] = entry;
            const json = JSON.stringify({ version: SNAPSHOT_VERSION, identity: opts.identity, savedAt: now(), entries: live });
            if (Buffer.byteLength(json) > MAX_SNAPSHOT_BYTES) return;
            fs.mkdirSync(path.dirname(snapshotFile), { recursive: true });
            const tmp = `${snapshotFile}.${process.pid}.tmp`;
            fs.writeFileSync(tmp, json);
            fs.renameSync(tmp, snapshotFile);
        } catch {
            counters.snapshotErrors += 1;
        }
    }

    /**
     * @param {string} key
     * @returns {{ value: any, ageMs: number } | undefined}
     */
    function get(key) {
        const e = entries.get(key);
        if (!e) return undefined;
        const ageMs = now() - e.storedAt;
        if (ttlMs <= 0 || ageMs >= ttlMs) {
            entries.delete(key);
            return undefined;
        }
        return { value: e.value, ageMs };
    }

    /**
     * @param {string} key
     * @param {any} value
     */
    function set(key, value) {
        if (ttlMs <= 0) return;
        entries.set(key, { storedAt: now(), value });
        saveSnapshot();
    }

    /**
     * @template T
     * @param {string} key
     * @param {() => Promise<T>} loader
     * @param {{ refresh?: boolean }} [o]
     * @returns {Promise<{ value: T, cached: boolean, ageMs: number }>}
     */
    async function getOrLoad(key, loader, o = {}) {
        if (!o.refresh) {
            const hit = get(key);
            if (hit) {
                counters.hits += 1;
                return { value: hit.value, cached: true, ageMs: hit.ageMs };
            }
        }
        counters.misses += 1;
        let pending = inflight.get(key);
        if (!pending) {
            counters.loads += 1;
            // The owner of the load stores the value once; callers that joined just await it.
            pending = loader()
                .then((v) => {
                    set(key, v);
                    return v;
                })
                .finally(() => inflight.delete(key));
            inflight.set(key, pending);
        }
        const value = await pending;
        return { value, cached: false, ageMs: 0 };
    }

    /** @param {string} [prefix] */
    function clear(prefix) {
        for (const key of [...entries.keys()]) if (!prefix || key.startsWith(prefix)) entries.delete(key);
        saveSnapshot();
    }

    function info() {
        let oldest = 0;
        for (const e of entries.values()) oldest = Math.max(oldest, now() - e.storedAt);
        return {
            enabled: ttlMs > 0,
            ttl_s: ttlMs / 1000,
            entries: entries.size,
            oldest_age_s: Math.round(oldest / 1000),
            snapshot_file: snapshotFile,
            ...counters,
        };
    }

    return { get, set, getOrLoad, clear, info };
}

/** @typedef {ReturnType<typeof createCache>} Cache */

/**
 * "cached 42 s ago" / "fresh" label for tool output.
 * @param {{ cached: boolean, ageMs: number }} r
 */
export function cacheLabel(r) {
    return r.cached ? `cached ${Math.round(r.ageMs / 1000)} s ago (pass refresh: true to re-read)` : 'fresh from the catalog';
}
