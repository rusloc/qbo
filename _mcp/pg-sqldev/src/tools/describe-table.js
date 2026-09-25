// @ts-check
import { z } from 'zod';
import { getCapabilities, withCitusFallback } from '../capabilities.js';
import { loadSql } from '../sql.js';
import { fmtCount, fmtBytes, fmtPct, clip, renderTable, applyBudget, nameMatcher } from '../format.js';
import { KIND_LABEL } from './schema-overview.js';

/** @typedef {import('../capabilities.js').Ctx} Ctx */

const TEXT_BUDGET = 60 * 1024;
const SHORT_DEFINITION_LINES = 40;
const MAX_AMBIGUOUS = 3;

/**
 * Parse "schema.table", 'schema."MixedCase"', '"Mixed"' or "table" the way PostgreSQL reads it:
 * unquoted parts fold to lower case, quoted parts are taken literally ("" is an escaped quote).
 * @param {string} raw
 * @returns {{ schema: string | null, name: string, error?: undefined } | { error: string }}
 */
export function parseRelationName(raw) {
    const text = raw.trim();
    if (!text) return { error: 'empty name' };
    /** @type {string[]} */
    const parts = [];
    let i = 0;
    while (i < text.length) {
        let part = '';
        if (text[i] === '"') {
            i += 1;
            let closed = false;
            while (i < text.length) {
                if (text[i] === '"' && text[i + 1] === '"') {
                    part += '"';
                    i += 2;
                } else if (text[i] === '"') {
                    closed = true;
                    i += 1;
                    break;
                } else {
                    part += text[i];
                    i += 1;
                }
            }
            if (!closed) return { error: 'unterminated quoted identifier' };
            if (!part) return { error: 'empty quoted identifier' };
        } else {
            while (i < text.length && text[i] !== '.' && text[i] !== '"') {
                part += text[i];
                i += 1;
            }
            part = part.trim().toLowerCase();
            if (!part) return { error: 'empty name part' };
            if (/\s/.test(part)) return { error: 'unquoted names cannot contain spaces: quote the name' };
        }
        parts.push(part);
        if (i < text.length) {
            if (text[i] !== '.') return { error: `unexpected character "${text[i]}" after a name part` };
            i += 1;
            if (i >= text.length) return { error: 'name ends with a dot' };
        }
    }
    if (parts.length === 1) return { schema: null, name: parts[0] };
    if (parts.length === 2) return { schema: parts[0], name: parts[1] };
    return { error: 'use schema.table: database-qualified names are not supported' };
}

/**
 * @param {number | null} nDistinct
 * @param {number | null} rows
 */
function fmtDistinct(nDistinct, rows) {
    if (nDistinct === null || nDistinct === undefined) return '';
    if (nDistinct === -1) return 'unique';
    if (nDistinct < 0) return rows && rows > 0 ? `~${fmtCount(Math.round(-nDistinct * rows))}` : `${Math.round(-nDistinct * 100)}% of rows`;
    return fmtCount(nDistinct);
}

/**
 * @param {unknown[] | null} values
 * @param {number[] | null} freqs
 */
function fmtTopValues(values, freqs) {
    if (!Array.isArray(values) || values.length === 0) return '';
    return values
        .slice(0, 3)
        .map((v, i) => `${clip(typeof v === 'string' ? v : JSON.stringify(v), 24)}${freqs?.[i] !== undefined ? ` ${fmtPct(freqs[i])}` : ''}`)
        .join(' | ');
}

/**
 * Fetch and shape the relations behind a list of parsed requests. Two catalog queries for the
 * whole batch: relations (+ keys + indexes as JSON), then columns (+ statistics).
 * @param {Ctx} ctx
 * @param {{ key: string, schema: string | null, name: string }[]} requests
 * @param {boolean} citus
 * @param {boolean} withDefinitions
 */
export async function fetchBatch(ctx, requests, citus, withDefinitions) {
    return ctx.db.readOnly(async (tx) => {
        const rels = await tx.query(`describe-relations${citus ? ' (citus)' : ''}`, loadSql('describe-relations', { citus }), [
            ctx.config.schemas,
            requests.map((r) => r.schema),
            requests.map((r) => r.name),
            withDefinitions,
        ]);
        const oids = [...new Set(rels.map((r) => Number(r._oid)))];
        const cols = oids.length ? await tx.query('describe-columns', loadSql('describe-columns'), [oids]) : [];

        /** @type {Map<number, any[]>} */
        const colsByOid = new Map();
        for (const c of cols) {
            const list = colsByOid.get(Number(c._oid)) ?? [];
            list.push({
                position: c._position,
                column: c._column,
                type: c._type,
                not_null: c._not_null === true,
                default: c._default ?? null,
                identity: c._identity || null,
                generated: c._generated || null,
                comment: c._comment ?? null,
                null_frac: c._null_frac ?? null,
                n_distinct: c._n_distinct ?? null,
                avg_width: c._avg_width ?? null,
                correlation: c._correlation ?? null,
                top_values: c._top_values ?? null,
                top_freqs: c._top_freqs ?? null,
            });
            colsByOid.set(Number(c._oid), list);
        }

        /** @type {Map<string, any[]>} */
        const byRequest = new Map(requests.map((r) => [r.key, []]));
        for (const r of rels) {
            const req = requests[Number(r._ord) - 1];
            const managed = Boolean(r._citus_type);
            byRequest.get(req.key)?.push({
                schema: r._schema,
                name: r._name,
                qualified: r._qualified,
                exact_match: r._exact_match === true,
                kind: r._kind,
                persistence: r._persistence,
                owner: r._owner,
                est_rows: managed || r._est_rows === null ? null : Number(r._est_rows),
                est_table_bytes: managed ? null : Number(r._est_table_bytes),
                est_index_bytes: managed ? null : Number(r._est_index_bytes),
                last_analyze: r._last_analyze ?? null,
                last_vacuum: r._last_vacuum ?? null,
                can_select: r._can_select === true,
                comment: r._comment ?? null,
                is_partition: r._is_partition === true,
                parent: r._parent ?? null,
                partition_key: r._partition_key ?? null,
                partitions: Number(r._partitions ?? 0),
                is_populated: r._is_populated ?? null,
                definition: r._definition ?? null,
                definition_fetched: withDefinitions,
                constraints: r._constraints ?? [],
                indexes: r._indexes ?? [],
                citus: managed
                    ? { type: r._citus_type, distribution_column: r._citus_distribution_column ?? null, colocation_id: r._citus_colocation_id ?? null, shards: r._citus_shards ?? null }
                    : null,
                columns: colsByOid.get(Number(r._oid)) ?? [],
            });
        }
        return byRequest;
    });
}

/**
 * @param {any} rel one shaped relation
 * @param {{ stats: boolean, definition: 'none' | 'short' | 'full', columnPattern?: string, caseNote: boolean }} o
 */
function renderRelation(rel, o) {
    const kind = KIND_LABEL[rel.kind] ?? rel.kind;
    const head = [`## ${rel.qualified} · ${kind}${rel.persistence === 'u' ? ' · unlogged' : ''}${rel.is_populated === false ? ' · NOT POPULATED' : ''}`];
    if (o.caseNote) head.push(`   matched case-insensitively. In SQL the name must be written exactly: ${rel.qualified}`);

    const facts = [];
    if (rel.kind !== 'v') {
        facts.push(`est rows ${fmtCount(rel.est_rows)}`);
        facts.push(`est size ${fmtBytes(rel.est_table_bytes)} table + ${fmtBytes(rel.est_index_bytes)} indexes`);
        facts.push(`analyzed ${rel.last_analyze ?? 'never (or stats not visible)'}`);
    }
    facts.push(`owner ${rel.owner}`);
    facts.push(`select ${rel.can_select ? 'yes' : 'NO'}`);
    head.push(`   ${facts.join(' · ')}`);
    if (rel.comment) head.push(`   comment: ${clip(rel.comment, 300)}`);
    if (rel.citus) {
        head.push(
            `   citus: ${rel.citus.type}${rel.citus.distribution_column ? ` on (${rel.citus.distribution_column})` : ''}` +
                `${rel.citus.shards ? ` · ${rel.citus.shards} shards` : ''}${rel.citus.colocation_id ? ` · colocation ${rel.citus.colocation_id}` : ''}` +
                ' · rows, size and column statistics live on the workers and are not read',
        );
    }
    if (rel.partition_key) head.push(`   partitioned by ${rel.partition_key} · ${rel.partitions} partitions`);
    if (rel.is_partition && rel.parent) head.push(`   partition of ${rel.parent}`);

    const match = nameMatcher(o.columnPattern);
    const cols = rel.columns.filter((/** @type {any} */ c) => match(c.column));
    const anyStats = rel.columns.some((/** @type {any} */ c) => c.null_frac !== null);
    const colDefs = [
        { key: 'position', label: '#', align: /** @type {const} */ ('right') },
        { key: 'column', label: 'column', max: 64 },
        { key: 'type', label: 'type', max: 40 },
        { key: 'nullable', label: 'null' },
        { key: 'default', label: 'default', max: 40 },
        ...(o.stats && anyStats
            ? [
                  { key: 'nulls', label: 'null%', align: /** @type {const} */ ('right') },
                  { key: 'distinct', label: 'distinct', align: /** @type {const} */ ('right') },
                  { key: 'top', label: 'top values', max: 90 },
              ]
            : []),
        { key: 'comment', label: 'comment', max: 80 },
    ];
    const body = [
        '',
        `columns (${cols.length}${cols.length !== rel.columns.length ? ` of ${rel.columns.length}, pattern "${o.columnPattern}"` : ''})`,
        renderTable(
            colDefs,
            cols.map((/** @type {any} */ c) => ({
                position: c.position,
                column: c.column,
                type: c.type,
                nullable: c.not_null ? 'no' : 'yes',
                default: c.identity ? `identity (${c.identity === 'a' ? 'always' : 'by default'})` : c.generated ? `generated: ${c.default ?? ''}` : c.default,
                nulls: fmtPct(c.null_frac),
                distinct: fmtDistinct(c.n_distinct, rel.est_rows),
                top: fmtTopValues(c.top_values, c.top_freqs),
                comment: c.comment,
            })),
            { indent: '  ' },
        ),
    ];
    if (o.stats && !anyStats && rel.kind !== 'v' && rel.columns.length) {
        body.push(
            rel.citus
                ? '  (no column statistics on the coordinator for a Citus-managed table)'
                : '  (no column statistics: never analyzed, or the role cannot select this relation)',
        );
    }

    // Primary key first, then unique, foreign, check, exclude: the order a reader asks the questions in.
    const rank = /** @type {Record<string, number>} */ ({ p: 0, u: 1, f: 2, c: 3, x: 4 });
    const own = rel.constraints
        .filter((/** @type {any} */ k) => !k.incoming)
        .sort((/** @type {any} */ x, /** @type {any} */ y) => (rank[x.type] ?? 9) - (rank[y.type] ?? 9) || String(x.name).localeCompare(String(y.name)));
    const incoming = rel.constraints.filter((/** @type {any} */ k) => k.incoming);
    const typeLabel = /** @type {Record<string, string>} */ ({ p: 'PK', u: 'UNIQUE', f: 'FK', c: 'CHECK', x: 'EXCLUDE' });
    /** @param {any} k */
    const keyLine = (k) => {
        if (k.type === 'f') {
            const arrow = `${k.from_table}(${(k.from_columns ?? []).join(', ')}) -> ${k.to_table}(${(k.to_columns ?? []).join(', ')})`;
            return `  ${k.incoming ? 'FK in ' : 'FK out'}  ${arrow}   [${k.name}]${k.validated === false ? ' NOT VALID' : ''}`;
        }
        return `  ${(typeLabel[k.type] ?? k.type).padEnd(6)}  ${clip(k.definition, 200)}   [${k.name}]`;
    };
    if (rel.kind !== 'v') {
        body.push('', `keys and constraints (${own.length} own, ${incoming.length} incoming foreign keys)`);
        if (rel.constraints.length === 0) body.push('  (none declared: grain and join paths must come from the docs or from join_paths)');
        else body.push(...own.map(keyLine), ...incoming.map(keyLine));

        body.push('', `indexes (${rel.indexes.length})`);
        if (rel.indexes.length === 0) body.push('  (none)');
        else {
            body.push(
                renderTable(
                    [
                        { key: 'definition', label: 'definition', max: 160 },
                        { key: 'scans', label: 'scans', align: 'right' },
                        { key: 'size', label: 'est size', align: 'right' },
                        { key: 'flags', label: 'flags' },
                    ],
                    rel.indexes.map((/** @type {any} */ x) => ({
                        definition: String(x.definition ?? '').replace(/^CREATE (UNIQUE )?INDEX /, (/** @type {string} */ _m, /** @type {string} */ u) => (u ? 'UNIQUE ' : '')),
                        scans: x.scans === null || x.scans === undefined ? '' : fmtCount(Number(x.scans)),
                        size: fmtBytes(Number(x.est_bytes)),
                        flags: [x.is_primary ? 'primary' : null, x.is_valid === false ? 'INVALID' : null].filter(Boolean).join(', '),
                    })),
                    { indent: '  ' },
                ),
            );
        }
    }

    if ((rel.kind === 'v' || rel.kind === 'm') && o.definition !== 'none') {
        if (rel.definition) {
            const lines = String(rel.definition).split('\n');
            const cut = o.definition === 'short' && lines.length > SHORT_DEFINITION_LINES;
            body.push(
                '',
                `definition (${cut ? `first ${SHORT_DEFINITION_LINES} of ${lines.length} lines, pass definition: "full" for all` : `${lines.length} lines`})`,
                ...(cut ? lines.slice(0, SHORT_DEFINITION_LINES) : lines).map((l) => `  ${l}`),
            );
        } else if (!rel.definition_fetched) {
            body.push('', 'definition: skipped, the relation was locked (see notes). Retry shortly.');
        }
    }
    return [...head, ...body].join('\n');
}

export const describeTable = {
    name: 'describe_table',
    title: 'Describe table',
    description:
        'Full metadata for up to 10 tables / views / materialized views per call: columns (type, nullability, default, comment) with planner statistics (null share, distinct estimate, top values), ' +
        'primary / unique / foreign keys in both directions, indexes with usage counts, partition and Citus distribution info, and the view definition. ' +
        'Names: schema.table, or schema."MixedCase" for quoted names; unqualified names are searched in all schemas in scope. ' +
        'Cost: two catalog queries per call for the whole batch, cached 10 minutes. Statistics come from pg_stats: no scan of the table itself.',
    input: {
        tables: z.array(z.string().min(1).max(200)).min(1).max(10).describe('1 to 10 relation names, e.g. ["portal.freight_unit_enrich", "portal.\\"PurchaseOrderLine\\""].'),
        stats: z.boolean().optional().describe('Show planner statistics per column. Default true.'),
        column_pattern: z.string().max(200).optional().describe('Only list columns whose name matches (contains, or * wildcard). Useful on very wide tables.'),
        definition: z.enum(['none', 'short', 'full']).optional().describe('View / matview SQL: none, short (first 40 lines, default), full.'),
        format: z.enum(['text', 'json']).optional().describe('Default "text".'),
        refresh: z.boolean().optional().describe('Bypass the cache and re-read the catalog.'),
    },

    /**
     * @param {Ctx} ctx
     * @param {{ tables: string[], stats?: boolean, column_pattern?: string, definition?: 'none' | 'short' | 'full', format?: 'text' | 'json', refresh?: boolean }} args
     */
    async handler(ctx, args) {
        const scope = ctx.config.schemas;
        /** @type {string[]} */
        const notes = [];

        // 1. Parse and de-duplicate the requests.
        /** @type {{ raw: string, key: string | null, schema: string | null, name: string, error: string | null }[]} */
        const parsed = args.tables.map((raw) => {
            const p = parseRelationName(raw);
            if (p.error !== undefined) return { raw, key: null, schema: null, name: '', error: p.error };
            if (p.schema && !scope.includes(p.schema)) {
                return { raw, key: null, schema: p.schema, name: p.name, error: `schema "${p.schema}" is not in scope (PG_SCHEMAS: ${scope.join(', ')})` };
            }
            return { raw, key: `describe:${p.schema ?? '*'}.${p.name}`, schema: p.schema, name: p.name, error: null };
        });

        // 2. Serve from cache, fetch the rest in one batch.
        /** @type {Map<string, { relations: any[], cached: boolean, ageMs: number }>} */
        const results = new Map();
        /** @type {{ key: string, schema: string | null, name: string }[]} */
        const toFetch = [];
        for (const p of parsed) {
            if (!p.key || results.has(p.key) || toFetch.some((t) => t.key === p.key)) continue;
            const hit = args.refresh ? undefined : ctx.cache.get(p.key);
            if (hit) results.set(p.key, { relations: hit.value, cached: true, ageMs: hit.ageMs });
            else toFetch.push({ key: p.key, schema: p.schema, name: p.name });
        }

        if (toFetch.length) {
            const caps = await getCapabilities(ctx);
            let withDefinitions = true;
            /** @type {Awaited<ReturnType<typeof withCitusFallback<Map<string, any[]>>>>} */
            let fetched;
            try {
                fetched = await withCitusFallback(caps.value.citus, (citus) => fetchBatch(ctx, toFetch, citus, true));
            } catch (e) {
                // pg_get_viewdef() needs a lock on the view. A materialized view that is being refreshed
                // without CONCURRENTLY holds an exclusive lock: retry once without definitions.
                if (/** @type {{ code?: string }} */ (e).code !== '55P03') throw e;
                withDefinitions = false;
                notes.push('Lock timeout while reading view definitions (a relation is locked, e.g. a materialized view refresh). Definitions were skipped; this result is not cached.');
                fetched = await withCitusFallback(caps.value.citus, (citus) => fetchBatch(ctx, toFetch, citus, false));
            }
            if (fetched.note) notes.push(fetched.note);
            for (const [key, relations] of fetched.result) {
                if (withDefinitions && relations.length) ctx.cache.set(key, relations);
                results.set(key, { relations, cached: false, ageMs: 0 });
            }
        }

        // 3. Pick the relation(s) per request: exact match wins, otherwise case-insensitive matches.
        const resolved = parsed.map((p) => {
            if (p.error || !p.key) return { request: p.raw, error: p.error, relations: [], case_insensitive: false, ambiguous: false, cached: false };
            const r = results.get(p.key);
            const all = r?.relations ?? [];
            const exact = all.filter((x) => x.exact_match);
            const chosen = exact.length ? exact : all;
            return {
                request: p.raw,
                error: chosen.length ? null : 'not found in the schemas in scope',
                relations: chosen.slice(0, MAX_AMBIGUOUS),
                case_insensitive: exact.length === 0 && chosen.length > 0,
                ambiguous: chosen.length > 1,
                cached: r?.cached ?? false,
            };
        });

        // Suggestions for misses come from the overview cache only: zero queries.
        const overview = ctx.cache.get('overview:all');
        /** @param {string} raw */
        const suggest = (raw) => {
            const p = parseRelationName(raw);
            if (p.error !== undefined || !overview) return [];
            const needle = p.name.toLowerCase();
            return /** @type {{ schema: string, name: string }[]} */ (overview.value.relations)
                .filter((r) => r.name.toLowerCase().includes(needle) || needle.includes(r.name.toLowerCase()))
                .slice(0, 5)
                .map((r) => `${r.schema}.${r.name}`);
        };

        if (args.format === 'json') {
            return JSON.stringify(
                {
                    tables: resolved.map((r) => ({ ...r, suggestions: r.error ? suggest(r.request) : undefined })),
                    notes,
                },
                null,
                1,
            );
        }

        const allCached = resolved.every((r) => r.cached || r.error);
        const out = [`describe_table · ${resolved.filter((r) => !r.error).length} of ${resolved.length} resolved · ${allCached ? 'served from cache' : 'fresh from the catalog'}`];
        for (const r of resolved) {
            out.push('');
            if (r.error) {
                const s = suggest(r.request);
                out.push(`## ${r.request} · NOT RESOLVED: ${r.error}${s.length ? `\n   did you mean: ${s.join(', ')}` : ''}`);
                continue;
            }
            if (r.ambiguous) out.push(`(!) "${r.request}" matches ${r.relations.length} relations. Qualify the name with a schema. All are shown.`);
            for (const rel of r.relations) {
                out.push(
                    renderRelation(rel, {
                        stats: args.stats !== false,
                        definition: args.definition ?? 'short',
                        columnPattern: args.column_pattern,
                        caseNote: r.case_insensitive,
                    }),
                );
            }
        }
        if (notes.length) out.push('', 'notes', ...notes.map((n) => `  - ${n}`));
        return applyBudget(out.join('\n'), TEXT_BUDGET, 'Describe fewer tables per call, pass column_pattern, stats: false, or definition: "none".').text;
    },
};
