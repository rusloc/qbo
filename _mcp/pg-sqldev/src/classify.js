// @ts-check
/**
 * Statement classifier: the first filter in front of the database.
 *
 * It is NOT the barrier. The barrier is the read-only transaction that db.js wraps around every
 * call, and behind that the privileges of the database role. This filter exists to refuse the
 * obvious early, with a clear reason, and to close the gaps a read-only transaction leaves open:
 *
 *   - statement stacking          "select 1; drop table t"
 *   - EXPLAIN ANALYZE             really executes its statement
 *   - data-modifying CTEs         "with x as (delete ...) select ..."
 *   - functions whose side effects escape the transaction: set_config, dblink, advisory locks,
 *     pg_terminate_backend, and on Citus run_command_on_workers and friends, which run their
 *     command on OTHER connections that are not read-only.
 *
 *   - functions that execute SQL handed to them as a string (query_to_xml, ts_stat, crosstab),
 *     because a denied function could hide inside that string
 *   - U&'...' / U&"..." unicode escapes, which PostgreSQL decodes before it resolves a name, so
 *     U&"pg\005fsleep"(1) would walk past any name-based rule
 *
 * Known limits, stated plainly. The read-only transaction is relied on to stop "select ... into t"
 * and user-defined functions that write. Nothing here can know what a user-defined or extension
 * function does internally: a function that is not on the denylist and escapes the transaction is
 * only stopped by the privileges of the database role. That is why a dedicated read-only role is
 * the recommended setup and this filter is not the barrier.
 *
 * The tokenizer mirrors PostgreSQL's lexer: its whitespace set, line comments ending at \n or \r,
 * nested block comments, '...' strings with '' escapes, E'...' strings with backslash escapes,
 * "quoted identifiers", and $tag$...$tag$ dollar quotes. Hardened after an adversarial review on
 * 2026-09-18; every finding of that review is a test case in test/classify.test.js.
 */

const ALLOWED_FIRST = new Set(['select', 'with', 'values', 'table', 'explain', 'show']);
const ALLOWED_INNER = new Set(['select', 'with', 'values', 'table']);
const DML_WORDS = new Set(['insert', 'update', 'delete', 'merge']);

/** Functions refused by exact name. */
const DENY_FUNCTIONS = new Set([
    // session / server state
    'set_config',
    'pg_reload_conf',
    'pg_rotate_logfile',
    'pg_switch_wal',
    'pg_promote',
    'pg_notify',
    'pg_export_snapshot',
    'pg_log_backend_memory_contexts',
    'pg_start_backup',
    'pg_stop_backup',
    // other sessions
    'pg_terminate_backend',
    'pg_cancel_backend',
    // transaction ids and sequences: consumed for good, a rollback does not give them back
    'txid_current',
    'pg_current_xact_id',
    'nextval',
    'setval',
    // shared buffers
    'pg_prewarm',
    'autoprewarm_start_worker',
    'autoprewarm_dump_now',
    // statistics resets
    'pg_stat_statements_reset',
    // server file system
    'pg_read_file',
    'pg_read_binary_file',
    'pg_stat_file',
    // large objects
    'lo_import',
    'lo_export',
    'lo_unlink',
    'lo_create',
    'lo_creat',
    'lo_put',
    'lo_from_bytea',
    'lowrite',
    'lo_truncate',
    'lo_truncate64',
    // Functions that EXECUTE SQL HANDED TO THEM AS A STRING. The classifier cannot see inside that
    // string, so a denied function could hide there: query_to_xml('select pg_terminate_backend(1)').
    'ts_stat',
    'ts_rewrite',
    'xpath_table',
    'connectby',
    // Citus: change cluster metadata or run commands on other connections
    'create_distributed_table',
    'create_distributed_table_concurrently',
    'create_distributed_function',
    'create_reference_table',
    'alter_distributed_table',
    'alter_table_set_access_method',
    'alter_old_partitions_set_access_method',
    'undistribute_table',
    'truncate_local_data_after_distributing_table',
    'remove_local_tables_from_metadata',
    'update_distributed_table_colocation',
    'mark_tables_colocated',
    'isolate_tenant_to_new_shard',
    'rebalance_table_shards',
    'replicate_table_shards',
    'replicate_reference_tables',
    'start_metadata_sync_to_node',
    'stop_metadata_sync_to_node',
    'recover_prepared_transactions',
    'create_time_partitions',
    'drop_old_time_partitions',
    'create_intermediate_result',
    'broadcast_intermediate_result',
]);

/** Functions refused by prefix. All of these are system or extension namespaces, not ordinary words. */
const DENY_PREFIXES = [
    'pg_sleep',
    'pg_advisory_',
    'pg_try_advisory_',
    'pg_stat_reset',
    'pg_replication_',
    'pg_logical_',
    'pg_create_',
    'pg_drop_',
    'pg_file_',
    'pg_backup_',
    'pg_wal_replay_',
    'pg_ls_',
    'pg_buffercache_evict',
    'binary_upgrade_',
    'dblink',
    'run_command_on_',
    'citus_',
    'query_to_xml',
    'cursor_to_xml',
    'table_to_xml',
    'schema_to_xml',
    'database_to_xml',
    'crosstab',
];

/**
 * `master_` and `worker_` are the legacy Citus UDF namespaces, but they are also ordinary words:
 * this database has a column called master_carrier. Only the Citus verb stems are refused, so a
 * user function such as master_carrier_lookup() stays usable.
 */
const DENY_PATTERNS = [
    /^master_(add|activate|disable|remove|update|drain|set|create|append|apply|modify|copy|move|drop|run|unmark|initialize|get_new|stage|dist)_/,
    /^master_(run_on_worker|drop_all_shards|drop_sequences)$/,
    /^worker_(apply|drop|create|fix|record|copy|split|nextval|adjust|change|append|repartition|cleanup|save|fetch|merge|range|hash_partition)_?/,
];

/** Any function called with one of these schema qualifiers is refused: cron.schedule(...), ... */
const DENY_SCHEMAS = new Set(['cron', 'citus_internal', 'partman']);

/** Read-only Citus helpers that stay allowed despite the `citus_` prefix rule. */
const ALLOW_FUNCTIONS = new Set(['citus_version', 'citus_table_size', 'citus_relation_size', 'citus_total_relation_size', 'citus_shard_sizes', 'citus_get_active_worker_nodes']);

/** PostgreSQL's own whitespace set. JS \s is wider (NBSP, BOM, U+2028) and would desync the lexer. */
const isSpace = (/** @type {string} */ ch) => ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r' || ch === '\f' || ch === '\v';

/**
 * @typedef {{ t: 'word' | 'qident' | 'str' | 'num' | 'param' | 'punct', v: string, pos: number }} Token
 */

const isIdentStart = (/** @type {string} */ ch) => /[A-Za-z_-￿]/.test(ch);
const isIdentPart = (/** @type {string} */ ch) => /[A-Za-z0-9_$-￿]/.test(ch);

/**
 * @param {string} sql
 * @returns {{ tokens: Token[], error?: string }}
 */
export function tokenize(sql) {
    /** @type {Token[]} */
    const tokens = [];
    const n = sql.length;
    let i = 0;
    while (i < n) {
        const ch = sql[i];
        const next = sql[i + 1];

        if (isSpace(ch)) {
            i += 1;
            continue;
        }
        if (ch === '-' && next === '-') {
            // PostgreSQL ends a line comment at \n OR at a bare \r. Ending it only at \n would let
            // "select 1 --\r; drop table t" hide its second statement from this tokenizer.
            let j = i + 2;
            while (j < n && sql[j] !== '\n' && sql[j] !== '\r') j += 1;
            i = j;
            continue;
        }
        if (ch === "'" || ch === '"') {
            // U&'...' and U&"..." carry unicode escapes that PostgreSQL decodes BEFORE it resolves a
            // name: U&"pg\005fsleep"(1) calls pg_sleep. Nothing here needs them, so they are refused
            // outright instead of decoded.
            const amp = tokens[tokens.length - 1];
            const u = tokens[tokens.length - 2];
            if (amp && u && amp.t === 'punct' && amp.v === '&' && amp.pos + 1 === i && u.t === 'word' && u.v === 'u' && u.pos + 1 === amp.pos) {
                return { tokens, error: 'unicode-escape strings and identifiers (U&) are not allowed' };
            }
        }
        if (ch === '/' && next === '*') {
            let depth = 1;
            let j = i + 2;
            while (j < n && depth > 0) {
                if (sql[j] === '/' && sql[j + 1] === '*') {
                    depth += 1;
                    j += 2;
                } else if (sql[j] === '*' && sql[j + 1] === '/') {
                    depth -= 1;
                    j += 2;
                } else {
                    j += 1;
                }
            }
            if (depth > 0) return { tokens, error: 'unterminated block comment' };
            i = j;
            continue;
        }
        if (ch === "'") {
            // E'...' honours backslash escapes; every other string form does not.
            const prev = tokens[tokens.length - 1];
            const isEscape = Boolean(prev && prev.t === 'word' && prev.v === 'e' && prev.pos + 1 === i);
            if (isEscape) tokens.pop();
            let j = i + 1;
            let closed = false;
            while (j < n) {
                if (isEscape && sql[j] === '\\') {
                    j += 2;
                } else if (sql[j] === "'" && sql[j + 1] === "'") {
                    j += 2;
                } else if (sql[j] === "'") {
                    closed = true;
                    j += 1;
                    break;
                } else {
                    j += 1;
                }
            }
            if (!closed) return { tokens, error: 'unterminated string literal' };
            tokens.push({ t: 'str', v: '', pos: i });
            i = j;
            continue;
        }
        if (ch === '"') {
            let j = i + 1;
            let closed = false;
            let content = '';
            while (j < n) {
                if (sql[j] === '"' && sql[j + 1] === '"') {
                    content += '"';
                    j += 2;
                } else if (sql[j] === '"') {
                    closed = true;
                    j += 1;
                    break;
                } else {
                    content += sql[j];
                    j += 1;
                }
            }
            if (!closed) return { tokens, error: 'unterminated quoted identifier' };
            tokens.push({ t: 'qident', v: content, pos: i });
            i = j;
            continue;
        }
        if (ch === '$') {
            const m = /^\$([A-Za-z_-￿][A-Za-z0-9_-￿]*)?\$/.exec(sql.slice(i, i + 130));
            if (m) {
                const tag = m[0];
                const end = sql.indexOf(tag, i + tag.length);
                if (end === -1) return { tokens, error: `unterminated dollar quote ${tag}` };
                tokens.push({ t: 'str', v: '', pos: i });
                i = end + tag.length;
                continue;
            }
            if (next !== undefined && /[0-9]/.test(next)) {
                let j = i + 1;
                while (j < n && /[0-9]/.test(sql[j])) j += 1;
                tokens.push({ t: 'param', v: sql.slice(i, j), pos: i });
                i = j;
                continue;
            }
            tokens.push({ t: 'punct', v: ch, pos: i });
            i += 1;
            continue;
        }
        if (isIdentStart(ch)) {
            let j = i + 1;
            while (j < n && isIdentPart(sql[j])) j += 1;
            tokens.push({ t: 'word', v: sql.slice(i, j).toLowerCase(), pos: i });
            i = j;
            continue;
        }
        if (/[0-9]/.test(ch)) {
            let j = i + 1;
            while (j < n && /[0-9A-Za-z_.]/.test(sql[j])) j += 1;
            tokens.push({ t: 'num', v: sql.slice(i, j), pos: i });
            i = j;
            continue;
        }
        tokens.push({ t: 'punct', v: ch, pos: i });
        i += 1;
    }
    return { tokens };
}

/**
 * First keyword of a statement, looking through leading parentheses: "(select ...) union ...".
 * @param {Token[]} tokens
 * @param {number} start
 */
function firstKeyword(tokens, start) {
    let i = start;
    let parens = 0;
    while (tokens[i] && tokens[i].t === 'punct' && tokens[i].v === '(') {
        parens += 1;
        i += 1;
    }
    const tok = tokens[i];
    return { word: tok && tok.t === 'word' ? tok.v : null, parens, index: i };
}

/**
 * Parse what follows EXPLAIN. Returns whether ANALYZE is requested and where the inner statement starts.
 * @param {Token[]} tokens
 */
function parseExplain(tokens) {
    let i = 1;
    let analyze = false;
    const falsy = new Set(['false', 'off', '0', 'f', 'no']);
    if (tokens[i] && tokens[i].t === 'punct' && tokens[i].v === '(') {
        // explain ( option [value] [, ...] ) statement
        // Only treat the parentheses as an option list when it does not start a statement.
        const peek = tokens[i + 1];
        const startsStatement = peek && peek.t === 'word' && ALLOWED_INNER.has(peek.v);
        if (!startsStatement) {
            let depth = 0;
            let expectName = true;
            for (; i < tokens.length; i += 1) {
                const tok = tokens[i];
                if (tok.t === 'punct' && tok.v === '(') {
                    depth += 1;
                    expectName = true;
                } else if (tok.t === 'punct' && tok.v === ')') {
                    depth -= 1;
                    if (depth === 0) {
                        i += 1;
                        break;
                    }
                } else if (tok.t === 'punct' && tok.v === ',') {
                    expectName = true;
                } else if (expectName && tok.t === 'word') {
                    if (tok.v === 'analyze' || tok.v === 'analyse') {
                        const val = tokens[i + 1];
                        const off = val && (val.t === 'word' || val.t === 'num') && falsy.has(val.v.toLowerCase());
                        if (!off) analyze = true;
                    }
                    expectName = false;
                }
            }
            if (depth !== 0) return { analyze, index: -1 };
        }
    } else {
        while (tokens[i] && tokens[i].t === 'word' && ['analyze', 'analyse', 'verbose'].includes(tokens[i].v)) {
            if (tokens[i].v !== 'verbose') analyze = true;
            i += 1;
        }
    }
    return { analyze, index: i };
}

/**
 * @param {string} sql
 * @param {{ allowAnalyze?: boolean }} [opts]
 * @returns {{ ok: true, keyword: string, explain: { analyze: boolean, inner: string } | null, statement: string }
 *          | { ok: false, reason: string }}
 */
export function classify(sql, opts = {}) {
    if (typeof sql !== 'string' || !sql.trim()) return { ok: false, reason: 'empty statement' };
    if (sql.includes(' ')) return { ok: false, reason: 'statement contains a NUL byte' };

    const { tokens, error } = tokenize(sql);
    if (error) return { ok: false, reason: error };
    if (tokens.length === 0) return { ok: false, reason: 'empty statement (comments only)' };

    // Single statement only. Trailing semicolons are fine, anything after one is not.
    const semi = tokens.findIndex((t) => t.t === 'punct' && t.v === ';');
    let body = tokens;
    let statement = sql;
    if (semi !== -1) {
        if (tokens.slice(semi).some((t) => !(t.t === 'punct' && t.v === ';'))) {
            return { ok: false, reason: 'multiple statements: only a single statement is allowed' };
        }
        body = tokens.slice(0, semi);
        statement = sql.slice(0, tokens[semi].pos);
    }
    if (body.length === 0) return { ok: false, reason: 'empty statement' };

    const first = firstKeyword(body, 0);
    if (!first.word) return { ok: false, reason: 'statement must start with a keyword' };
    if (!ALLOWED_FIRST.has(first.word)) {
        return { ok: false, reason: `"${first.word}" statements are not allowed. Allowed: select, with, values, table, explain, show` };
    }
    if (first.parens > 0 && !ALLOWED_INNER.has(first.word)) {
        return { ok: false, reason: `"${first.word}" cannot be parenthesised` };
    }

    /** @type {{ analyze: boolean, inner: string } | null} */
    let explain = null;
    if (first.word === 'explain') {
        const ex = parseExplain(body);
        if (ex.index === -1) return { ok: false, reason: 'explain: unbalanced option list' };
        const inner = firstKeyword(body, ex.index);
        if (!inner.word || !ALLOWED_INNER.has(inner.word)) {
            return { ok: false, reason: `explain of "${inner.word ?? '?'}" is not allowed. Allowed: select, with, values, table` };
        }
        if (ex.analyze && !opts.allowAnalyze) {
            return { ok: false, reason: 'explain analyze executes the statement and needs an explicit opt-in' };
        }
        explain = { analyze: ex.analyze, inner: inner.word };
    }

    for (let i = 0; i < body.length; i += 1) {
        const tok = body[i];
        const before = body[i - 1];
        const after = body[i + 1];

        // A bare insert / update / delete / merge keyword anywhere in the statement. This covers every
        // shape a write can take behind an allowed first keyword:
        //     with x as (delete from t returning *) select ...      data-modifying CTE
        //     with x as (select 1) delete from t                    top-level DML after a CTE list
        //     (with y as (select 1) update t set ...)               nested
        //     select ... for update                                 row locks
        // A column that really carries such a name still works qualified (t.update) or quoted ("update").
        if (tok.t === 'word' && DML_WORDS.has(tok.v) && !(before && before.t === 'punct' && before.v === '.')) {
            return {
                ok: false,
                reason: `data-modifying or locking keyword "${tok.v}" is not allowed. If it is a column or alias name, qualify it (t.${tok.v}) or quote it ("${tok.v}")`,
            };
        }

        // Function calls with side effects that escape a read-only transaction.
        if ((tok.t === 'word' || tok.t === 'qident') && after && after.t === 'punct' && after.v === '(') {
            const name = tok.v.toLowerCase();
            const qualifier = before && before.t === 'punct' && before.v === '.' ? body[i - 2] : null;
            if (qualifier && (qualifier.t === 'word' || qualifier.t === 'qident') && DENY_SCHEMAS.has(qualifier.v.toLowerCase())) {
                return { ok: false, reason: `functions in schema "${qualifier.v.toLowerCase()}" are not allowed` };
            }
            if (ALLOW_FUNCTIONS.has(name)) continue;
            if (DENY_FUNCTIONS.has(name) || DENY_PREFIXES.some((p) => name.startsWith(p)) || DENY_PATTERNS.some((rx) => rx.test(name))) {
                return { ok: false, reason: `function "${name}" is not allowed` };
            }
        }
    }

    return { ok: true, keyword: first.word, explain, statement };
}
