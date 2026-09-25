// @ts-check
/**
 * Loader for the catalog queries in src/sql/*.sql.
 *
 * One file per query. A file can carry variant blocks so the Citus and the plain form of a
 * query stay side by side in a single place:
 *
 *     -- #if citus
 *     ...lines kept only when the flag is on...
 *     -- #else
 *     ...lines kept only when the flag is off...
 *     -- #endif
 *
 * No nesting. Flags are booleans chosen by the server (never user input), so this is templating
 * of trusted text, not SQL building. Values always travel as bind parameters.
 */
import fs from 'node:fs';
import path from 'node:path';
import { SERVER_DIR } from './config.js';

const SQL_DIR = path.join(SERVER_DIR, 'src', 'sql');
/** @type {Map<string, string>} */
const rawCache = new Map();

/**
 * @param {string} text
 * @param {Record<string, boolean>} flags
 */
export function preprocess(text, flags) {
    const out = [];
    /** @type {boolean | null} */
    let keep = null; // null = outside any block
    for (const line of text.split(/\r?\n/)) {
        const m = line.match(/^\s*--\s*#(if|else|endif)\b\s*(!?)\s*(\w+)?\s*$/);
        if (!m) {
            if (keep === null || keep) out.push(line);
            continue;
        }
        const [, directive, negate, flag] = m;
        if (directive === 'if') {
            if (keep !== null) throw new Error('sql preprocess: nested #if is not supported');
            if (!flag) throw new Error('sql preprocess: #if needs a flag name');
            const on = Boolean(flags[flag]);
            keep = negate ? !on : on;
        } else if (directive === 'else') {
            if (keep === null) throw new Error('sql preprocess: #else without #if');
            keep = !keep;
        } else {
            if (keep === null) throw new Error('sql preprocess: #endif without #if');
            keep = null;
        }
    }
    if (keep !== null) throw new Error('sql preprocess: unterminated #if');
    return out.join('\n');
}

/**
 * @param {string} name file name without extension, e.g. "schema-overview"
 * @param {Record<string, boolean>} [flags]
 */
export function loadSql(name, flags = {}) {
    if (!/^[a-z0-9-]+$/.test(name)) throw new Error(`bad sql name: ${name}`);
    let raw = rawCache.get(name);
    if (raw === undefined) {
        raw = fs.readFileSync(path.join(SQL_DIR, `${name}.sql`), 'utf8');
        rawCache.set(name, raw);
    }
    return preprocess(raw, flags);
}

export function listSqlFiles() {
    return fs
        .readdirSync(SQL_DIR)
        .filter((f) => f.endsWith('.sql'))
        .map((f) => f.slice(0, -4))
        .sort();
}
