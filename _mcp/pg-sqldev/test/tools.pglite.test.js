// @ts-check
/**
 * Integration test of the three increment-1 tools against a real PostgreSQL engine (PGlite, the
 * WASM build of Postgres) with a fixture shaped like the source project's database. No network, no
 * credentials. It proves the catalog SQL, the guards and the accounting; it cannot prove
 * anything about Azure, TLS, Citus or the real data volumes: that is what probe + smoke are for.
 */
import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { PGlite } from '@electric-sql/pglite';
import { loadConfig } from '../src/config.js';
import { createDb, RefusedError } from '../src/db.js';
import { createCache } from '../src/cache.js';
import { classify } from '../src/classify.js';
import { loadSql, listSqlFiles } from '../src/sql.js';
import { runTool } from '../src/server.js';
import { tools } from '../src/registry.js';
import { parseRelationName } from '../src/tools/describe-table.js';
import { familyOf } from '../src/tools/schema-overview.js';

const FIXTURE = `
create schema portal;
create schema portal_dev;

create table portal."PurchaseOrderLine" (
    id          bigint primary key,
    po_number   text not null,
    sku         text,
    qty         numeric(12,2) default 0,
    status      text,
    created_at  timestamptz default now()
);
comment on table portal."PurchaseOrderLine" is 'One row per purchase order line. Grain: PO line.';
comment on column portal."PurchaseOrderLine".po_number is 'Client purchase order number';

create table portal.purchase_order_company (id int primary key, name text not null);
create table portal.freight_unit (id bigint primary key, serial_no text unique, status text);
create table portal.purchase_order_on_freight_unit (
    id                          bigint generated always as identity primary key,
    purchase_order_id           bigint references portal."PurchaseOrderLine" (id),
    freight_unit_id             bigint references portal.freight_unit (id),
    purchase_order_company_id   int references portal.purchase_order_company (id)
);
create index pofu_freight_unit_idx on portal.purchase_order_on_freight_unit (freight_unit_id);

create table portal.freight_unit_enrich (freight_unit_id bigint, _ship_response jsonb, _loaded timestamptz);
create table portal_dev.freight_unit (id bigint primary key, serial_no text);

create table public.sql_source (_report text not null, _page text not null, _code text, _updated timestamptz, unique (_report, _page));
create table public.focus__shipments (id int primary key, country text);
create table public.focus__containers (id int primary key);
create table public.dax__dim_date (d date primary key);
create table public.never_analyzed (id int);

create table public.events (id int, d date not null) partition by range (d);
create table public.events_2026_q1 partition of public.events for values from ('2026-01-01') to ('2026-04-01');
create table public.events_2026_q2 partition of public.events for values from ('2026-04-01') to ('2026-07-01');

create view public.focus__shipments_v as
select s.id _id, s.country _country
from public.focus__shipments s
where 1=1 and s.country is not null;

create materialized view portal.tracker_mv as
select
     f.id _freight_unit_id
    ,f.serial_no _serial_no
    ,p.po_number _po_number
from portal.freight_unit f
left join portal.purchase_order_on_freight_unit o on o.freight_unit_id = f.id
left join portal."PurchaseOrderLine" p on p.id = o.purchase_order_id;

insert into portal."PurchaseOrderLine" (id, po_number, sku, qty, status)
select g, 'PO-' || g, 'SKU-' || (g % 7), g % 13, case when g % 10 < 7 then 'OPEN' when g % 10 < 9 then 'CLOSED' else null end
from generate_series(1, 500) g;
insert into portal.freight_unit select g, 'FU' || g, 'x' from generate_series(1, 200) g;
insert into portal.purchase_order_company values (1, 'Contoso');
insert into portal.purchase_order_on_freight_unit (purchase_order_id, freight_unit_id, purchase_order_company_id)
select g, (g % 200) + 1, 1 from generate_series(1, 500) g;
insert into public.focus__shipments select g, case when g % 3 = 0 then 'AE' else 'SA' end from generate_series(1, 300) g;
insert into public.events select g, date '2026-01-01' + (g % 150) from generate_series(1, 400) g;
refresh materialized view portal.tracker_mv;

-- 400 extra relations, to prove the default overview stays under its output budget.
do $$
begin
    for i in 1..400 loop
        execute format('create table public.bulk__t%s (id int, payload text)', lpad(i::text, 3, '0'));
    end loop;
end $$;

analyze;
`;

const CITUS_FAKE = `
create table public.pg_dist_partition (logicalrelid regclass, partmethod "char", partkey text, colocationid int, repmodel "char");
create table public.pg_dist_shard (logicalrelid regclass, shardid bigint);
create function public.column_to_column_name(regclass, text) returns text language sql immutable as $f$ select $2 $f$;
insert into public.pg_dist_partition values ('portal.freight_unit', 'h', 'id', 7, 's'), ('portal.purchase_order_company', 'n', null, 8, 't');
insert into public.pg_dist_shard select 'portal.freight_unit'::regclass, g from generate_series(1, 32) g;
`;

/** @type {PGlite} */
let pg;
/** Every statement text sent to the engine, for assertions about what reached the database. */
/** @type {string[]} */
let wire = [];
/** @type {((q: { text: string, values?: unknown[] }) => void) | null} */
let intercept = null;

function pgliteDriver() {
    return {
        connect: async () => ({
            /** @param {string | { text: string, values?: unknown[] }} q */
            query: async (q) => {
                if (typeof q === 'string') {
                    wire.push(q);
                    await pg.exec(q);
                    return { rows: [] };
                }
                wire.push(q.text);
                if (intercept) intercept(q);
                const res = await pg.query(q.text, /** @type {any[]} */ (q.values ?? []));
                return { rows: /** @type {any[]} */ (res.rows) };
            },
            release() {},
        }),
        end: async () => {},
    };
}

function makeCtx() {
    const config = loadConfig({ envFile: 'Z:/none.env', env: {} });
    const db = createDb(config, { driver: pgliteDriver() });
    const cache = createCache({ ttlMs: 600_000, identity: 'pglite' });
    return { config, db, cache, version: 'test' };
}

/**
 * @param {ReturnType<typeof makeCtx>} ctx
 * @param {string} name
 * @param {any} [args]
 */
async function call(ctx, name, args = {}) {
    const tool = tools.find((t) => t.name === name);
    assert.ok(tool, `tool ${name} is registered`);
    const before = ctx.db.stats.catalogQueries;
    const r = await runTool(ctx, /** @type {any} */ (tool), args);
    return { text: r.content[0].text, isError: r.isError === true, queries: ctx.db.stats.catalogQueries - before };
}

before(async () => {
    pg = new PGlite();
    await pg.exec(FIXTURE);
});
after(async () => {
    await pg.close();
});

describe('guards (A3, against a real engine)', () => {
    test('every call runs inside begin read only + set local, and ends with rollback', async () => {
        const ctx = makeCtx();
        wire = [];
        await call(ctx, 'connection_info');
        assert.match(wire[0], /^begin transaction read only; set local statement_timeout = 15000; set local lock_timeout = 2000; set local idle_in_transaction_session_timeout = \d+$/);
        assert.equal(wire[wire.length - 1], 'rollback');
        assert.ok(!wire.some((w) => /\bset\s+(session\s+)?(?!local)\w+\s*(=|to)/i.test(w.replace(/set local/gi, ''))), 'no session-level SET is ever sent');
    });

    test('the guards are in force as seen from inside the transaction', async () => {
        const ctx = makeCtx();
        const { text } = await call(ctx, 'connection_info');
        assert.match(text, /transaction_read_only=on/);
        assert.match(text, /statement_timeout=15s/);
        assert.match(text, /lock_timeout=2s/);
        assert.doesNotMatch(text, /GUARD FAILURE/);
    });

    test('a write inside the guarded transaction is stopped by the server (25006)', async () => {
        const ctx = makeCtx();
        await assert.rejects(
            ctx.db.readOnly((tx) => tx.query('write attempt', "insert into public.sql_source values ('x', 'y', 'z', now())")),
            (e) => /** @type {any} */ (e).code === '25006',
        );
        const n = await pg.query("select count(*)::int n from public.sql_source where _report = 'x'");
        assert.equal(/** @type {any} */ (n.rows[0]).n, 0);
    });

    test('the transaction is rolled back and the connection stays usable after an error', async () => {
        const ctx = makeCtx();
        await assert.rejects(ctx.db.readOnly((tx) => tx.query('bad', 'select * from no_such_table')));
        const rows = await ctx.db.readOnly((tx) => tx.query('ok', 'select 1 _one'));
        assert.equal(rows[0]._one, 1);
        assert.equal(ctx.db.stats.errors, 1);
    });

    test('outside statements: the classifier refuses before anything reaches the database', async () => {
        const ctx = makeCtx();
        wire = [];
        await assert.rejects(
            ctx.db.readOnly((tx) => tx.guardedUserQuery('user', 'delete from public.sql_source')),
            (e) => e instanceof RefusedError,
        );
        await assert.rejects(
            ctx.db.readOnly((tx) => tx.guardedUserQuery('user', 'select 1; drop table public.sql_source')),
            (e) => e instanceof RefusedError && /multiple statements/.test(e.message),
        );
        assert.ok(!wire.some((w) => /delete from|drop table/.test(w)), 'refused text never went over the wire');
    });

    test('known classifier pass-through "select ... into" is stopped by the read-only transaction', async () => {
        const ctx = makeCtx();
        assert.equal(classify('select 1 _a into public.sneaky').ok, true, 'documented pass-through');
        await assert.rejects(
            ctx.db.readOnly((tx) => tx.guardedUserQuery('user', 'select 1 _a into public.sneaky')),
            (e) => /** @type {any} */ (e).code === '25006',
        );
    });

    test('every catalog query shipped in src/sql passes the classifier, in both variants', () => {
        const files = listSqlFiles();
        assert.ok(files.length >= 5);
        for (const f of files) {
            for (const citus of [false, true]) {
                const verdict = classify(loadSql(f, { citus }));
                assert.equal(verdict.ok, true, `${f} (citus=${citus}): ${verdict.ok ? '' : verdict.reason}`);
            }
        }
    });

    test('no catalog query names a user schema or calls a size function', () => {
        for (const f of listSqlFiles()) {
            const sql = loadSql(f, { citus: true }).replace(/--.*$/gm, '');
            assert.doesNotMatch(sql, /\b(portal|portal_dev)\./, `${f} must not reference user schemas`);
            assert.doesNotMatch(sql, /pg_(total_)?relation_size|pg_table_size|pg_indexes_size|count\(\*\)\s+from\s+(?!pg_|_rel)/i, `${f} must not call size functions`);
        }
    });
});

describe('connection_info (A5)', () => {
    test('reports version, citus flag, role, guards and schemas in scope: one catalog query', async () => {
        const ctx = makeCtx();
        const r = await call(ctx, 'connection_info');
        assert.equal(r.isError, false, r.text);
        assert.equal(r.queries, 1);
        assert.match(r.text, /postgres {4}\d+\.\d+/);
        assert.match(r.text, /citus {7}not installed/);
        assert.match(r.text, /role {8}\w+/);
        assert.match(r.text, /schemas {5}public \(ok\) · portal \(ok\) · portal_dev \(ok\)/);
        assert.match(r.text, /pool max 2/);
    });

    test('a schema that does not exist is called out', async () => {
        const ctx = makeCtx();
        ctx.config.schemas.push('ghost');
        const r = await call(ctx, 'connection_info');
        assert.match(r.text, /ghost \(MISSING\)/);
        assert.match(r.text, /Schema "ghost" does not exist/);
    });

    test('json format parses and carries no password field value', async () => {
        const ctx = makeCtx();
        const r = await call(ctx, 'connection_info', { format: 'json' });
        const data = JSON.parse(r.text);
        assert.equal(data.guards.transaction_read_only, 'on');
        assert.equal(JSON.stringify(data).includes('password'), false);
    });
});

describe('schema_overview (A6)', () => {
    test('relation counts match a direct catalog count', async () => {
        const ctx = makeCtx();
        const direct = await pg.query(
            `select count(*)::int n from pg_class c join pg_namespace n on n.oid = c.relnamespace
             where n.nspname in ('public', 'portal', 'portal_dev') and c.relkind in ('r', 'p', 'v', 'm', 'f')`,
        );
        const total = /** @type {any} */ (direct.rows[0]).n;
        const r = await call(ctx, 'schema_overview', { include_partitions: true, format: 'json', limit: 1000 });
        const data = JSON.parse(r.text);
        assert.equal(data.total_in_scope, total);
        assert.equal(data.matched, total);
        assert.equal(data.relations.length, total);
    });

    test('default output stays under 25 KB with 400+ relations, and says what was left out', async () => {
        const ctx = makeCtx();
        const r = await call(ctx, 'schema_overview');
        assert.equal(r.isError, false, r.text);
        assert.ok(Buffer.byteLength(r.text) < 25 * 1024, `size ${Buffer.byteLength(r.text)}`);
        assert.match(r.text, /more relations not listed/);
        assert.match(r.text, /bulk__\s+400/);
    });

    test('cold call costs at most two catalog queries; a warm call costs zero', async () => {
        const ctx = makeCtx();
        const cold = await call(ctx, 'schema_overview');
        const warm = await call(ctx, 'schema_overview');
        const otherFilter = await call(ctx, 'schema_overview', { pattern: 'focus__*', kinds: ['table'], sort: 'name' });
        assert.ok(cold.queries <= 2, `cold = ${cold.queries}`);
        assert.equal(warm.queries, 0);
        assert.equal(otherFilter.queries, 0, 'filters run in memory on the cached list');
        assert.match(warm.text, /cached \d+ s ago/);
    });

    test('refresh: true goes back to the catalog', async () => {
        const ctx = makeCtx();
        await call(ctx, 'schema_overview');
        const r = await call(ctx, 'schema_overview', { refresh: true });
        assert.equal(r.queries, 1);
    });

    test('pattern, kinds, family grouping', async () => {
        const ctx = makeCtx();
        const r = await call(ctx, 'schema_overview', { pattern: 'focus__*' });
        assert.match(r.text, /3 of \d+ relations/);
        assert.match(r.text, /public\.focus__shipments\s+table\s+300/);
        assert.match(r.text, /public\.focus__shipments_v\s+view/);
        assert.match(r.text, /focus__\s+3/);
        const mv = await call(ctx, 'schema_overview', { kinds: ['matview'] });
        assert.match(mv.text, /portal\.tracker_mv\s+matview/);
        assert.match(mv.text, /1 of \d+ relations/);
    });

    test('partitions are folded into the parent by default', async () => {
        const ctx = makeCtx();
        const folded = await call(ctx, 'schema_overview', { pattern: 'events*' });
        assert.match(folded.text, /public\.events\s+partitioned\s+400\s+.*2 partitions/);
        assert.doesNotMatch(folded.text, /events_2026_q1/);
        const listed = await call(ctx, 'schema_overview', { pattern: 'events*', include_partitions: true });
        assert.match(listed.text, /events_2026_q1.*is partition/);
    });

    test('quoted mixed-case names are shown the way SQL needs them', async () => {
        const ctx = makeCtx();
        const r = await call(ctx, 'schema_overview', { pattern: 'purchaseorderline' });
        assert.match(r.text, /portal\."PurchaseOrderLine"\s+table\s+500/);
        assert.match(r.text, /One row per purchase order line/);
    });

    test('never-analyzed tables show "?" instead of a wrong zero', async () => {
        const fresh = new PGlite();
        await fresh.exec('create table public.t_new (id int)');
        const saved = pg;
        pg = fresh;
        try {
            const ctx = makeCtx();
            const r = await call(ctx, 'schema_overview', { pattern: 't_new' });
            assert.match(r.text, /public\.t_new\s+table\s+\?/);
        } finally {
            pg = saved;
            await fresh.close();
        }
    });

    test('a schema outside the scope is refused without a query', async () => {
        const ctx = makeCtx();
        const r = await call(ctx, 'schema_overview', { schemas: ['pg_catalog'] });
        assert.equal(r.isError, true);
        assert.match(r.text, /not in scope/);
        assert.equal(r.queries, 0);
    });
});

describe('describe_table (A7)', () => {
    test('the four reference shapes in one batch: at most three catalog queries cold, zero warm', async () => {
        const ctx = makeCtx();
        const tables = ['portal.freight_unit_enrich', 'portal."PurchaseOrderLine"', 'public.sql_source', 'portal.tracker_mv'];
        const cold = await call(ctx, 'describe_table', { tables });
        assert.equal(cold.isError, false, cold.text);
        assert.ok(cold.queries <= 3, `cold = ${cold.queries}`);
        assert.match(cold.text, /4 of 4 resolved/);
        const warm = await call(ctx, 'describe_table', { tables });
        assert.equal(warm.queries, 0);
        assert.match(warm.text, /served from cache/);
    });

    test('quoted mixed-case name resolves; columns, comments, defaults and statistics are there', async () => {
        const ctx = makeCtx();
        const { text } = await call(ctx, 'describe_table', { tables: ['portal."PurchaseOrderLine"'] });
        assert.match(text, /## portal\."PurchaseOrderLine" · table/);
        assert.match(text, /est rows 500/);
        assert.match(text, /comment: One row per purchase order line/);
        assert.match(text, /po_number\s+text\s+no\b.*Client purchase order number/);
        assert.match(text, /qty\s+numeric\(12,2\)\s+yes\s+0\b/);
        assert.match(text, /\bid\s+bigint\s+no\b.*unique/);
        assert.match(text, /status\s+text\s+yes\s+10%\s+2\s+OPEN 70% \| CLOSED 20%/);
        assert.doesNotMatch(text, /matched case-insensitively/);
    });

    test('the documented relationship shows up from both sides', async () => {
        const ctx = makeCtx();
        const { text } = await call(ctx, 'describe_table', { tables: ['portal."PurchaseOrderLine"', 'portal.purchase_order_on_freight_unit'] });
        const arrow = 'portal.purchase_order_on_freight_unit(purchase_order_id) -> portal."PurchaseOrderLine"(id)';
        assert.ok(text.includes(`FK in   ${arrow}`), 'incoming on PurchaseOrderLine');
        assert.ok(text.includes(`FK out  ${arrow}`), 'outgoing on purchase_order_on_freight_unit');
        assert.match(text, /PK\s+PRIMARY KEY \(id\)/);
        assert.match(text, /\n {2}pofu_freight_unit_idx ON portal\.purchase_order_on_freight_unit USING btree \(freight_unit_id\)/);
        assert.ok(
            text.indexOf('PK      PRIMARY KEY (id)   [purchase_order_on_freight_unit_pkey]') < text.indexOf('FK out  portal.purchase_order_on_freight_unit(freight_unit_id)'),
            'the primary key is listed before the foreign keys',
        );
        assert.match(text, /identity \(always\)/);
    });

    test('an unquoted mixed-case name still resolves, with the exact spelling spelled out', async () => {
        const ctx = makeCtx();
        const { text } = await call(ctx, 'describe_table', { tables: ['portal.PurchaseOrderLine'] });
        assert.match(text, /1 of 1 resolved/);
        assert.match(text, /matched case-insensitively\. In SQL the name must be written exactly: portal\."PurchaseOrderLine"/);
    });

    test('public.sql_source: unique key and the wide _code column', async () => {
        const ctx = makeCtx();
        const { text } = await call(ctx, 'describe_table', { tables: ['public.sql_source'] });
        assert.match(text, /UNIQUE\s+UNIQUE \(_report, _page\)/);
        assert.match(text, /_code\s+text/);
    });

    test('materialized view: definition, short by default, none on request', async () => {
        const ctx = makeCtx();
        const short = await call(ctx, 'describe_table', { tables: ['portal.tracker_mv'] });
        assert.match(short.text, /## portal\.tracker_mv · matview/);
        assert.match(short.text, /definition \(\d+ lines\)/);
        assert.match(short.text, /LEFT JOIN portal\."PurchaseOrderLine" p ON/);
        const none = await call(ctx, 'describe_table', { tables: ['portal.tracker_mv'], definition: 'none' });
        assert.doesNotMatch(none.text, /LEFT JOIN/);
        assert.equal(none.queries, 0, 'rendering options never cost a query');
    });

    test('view: no keys section, no size, has definition', async () => {
        const ctx = makeCtx();
        const { text } = await call(ctx, 'describe_table', { tables: ['public.focus__shipments_v'] });
        assert.match(text, /· view/);
        assert.doesNotMatch(text, /keys and constraints/);
        assert.match(text, /FROM focus__shipments s/);
    });

    test('partitioned parent and partition child', async () => {
        const ctx = makeCtx();
        const { text } = await call(ctx, 'describe_table', { tables: ['public.events', 'public.events_2026_q1'] });
        assert.match(text, /partitioned by RANGE \(d\) · 2 partitions/);
        assert.match(text, /partition of public\.events/);
    });

    test('unqualified name that exists in two schemas is flagged as ambiguous', async () => {
        const ctx = makeCtx();
        const { text } = await call(ctx, 'describe_table', { tables: ['freight_unit'] });
        assert.match(text, /"freight_unit" matches 2 relations/);
        assert.match(text, /## portal\.freight_unit · table/);
        assert.match(text, /## portal_dev\.freight_unit · table/);
    });

    test('misses: not found, out of scope, malformed. The rest of the batch still works', async () => {
        const ctx = makeCtx();
        await call(ctx, 'schema_overview');
        const { text, isError } = await call(ctx, 'describe_table', {
            tables: ['portal.freight_unit_enrichh', 'pg_catalog.pg_class', 'portal."open', 'a.b.c', 'portal.freight_unit'],
        });
        assert.equal(isError, false);
        assert.match(text, /1 of 5 resolved/);
        assert.match(text, /freight_unit_enrichh · NOT RESOLVED: not found.*\n\s+did you mean: .*portal\.freight_unit_enrich/);
        assert.match(text, /pg_catalog\.pg_class · NOT RESOLVED: schema "pg_catalog" is not in scope/);
        assert.match(text, /NOT RESOLVED: unterminated quoted identifier/);
        assert.match(text, /NOT RESOLVED: use schema\.table/);
        assert.match(text, /## portal\.freight_unit · table/);
    });

    test('column_pattern and stats: false shrink the output', async () => {
        const ctx = makeCtx();
        const full = await call(ctx, 'describe_table', { tables: ['portal."PurchaseOrderLine"'] });
        const slim = await call(ctx, 'describe_table', { tables: ['portal."PurchaseOrderLine"'], column_pattern: 'po_*', stats: false });
        assert.match(slim.text, /columns \(1 of 6, pattern "po_\*"\)/);
        assert.doesNotMatch(slim.text, /top values/);
        assert.ok(slim.text.length < full.text.length);
    });

    test('a table with no declared keys says so, because that is the common case here', async () => {
        const ctx = makeCtx();
        const { text } = await call(ctx, 'describe_table', { tables: ['portal.freight_unit_enrich'] });
        assert.match(text, /none declared: grain and join paths must come from the docs/);
    });

    test('never analyzed: says why statistics are missing', async () => {
        const fresh = new PGlite();
        await fresh.exec('create table public.t_new (id int, v text)');
        const saved = pg;
        pg = fresh;
        try {
            const ctx = makeCtx();
            const { text } = await call(ctx, 'describe_table', { tables: ['public.t_new'] });
            assert.match(text, /est rows \?/);
            assert.match(text, /no column statistics: never analyzed/);
        } finally {
            pg = saved;
            await fresh.close();
        }
    });

    test('lock timeout on view definitions: retried without them, flagged, not cached', async () => {
        const ctx = makeCtx();
        intercept = (q) => {
            if (/pg_get_viewdef/.test(q.text) && q.values?.[3] === true) throw Object.assign(new Error('canceling statement due to lock timeout'), { code: '55P03' });
        };
        try {
            const r = await call(ctx, 'describe_table', { tables: ['portal.tracker_mv'] });
            assert.equal(r.isError, false, r.text);
            assert.match(r.text, /Lock timeout while reading view definitions/);
            assert.match(r.text, /definition: skipped/);
            assert.equal(ctx.cache.get('describe:portal.tracker_mv'), undefined);
        } finally {
            intercept = null;
        }
        const again = await call(ctx, 'describe_table', { tables: ['portal.tracker_mv'] });
        assert.match(again.text, /LEFT JOIN/);
    });

    test('json format parses', async () => {
        const ctx = makeCtx();
        const { text } = await call(ctx, 'describe_table', { tables: ['portal.freight_unit'], format: 'json' });
        const data = JSON.parse(text);
        assert.equal(data.tables[0].relations[0].qualified, 'portal.freight_unit');
        assert.equal(data.tables[0].relations[0].columns.length, 3);
    });
});

describe('citus branch (simulated metadata: proves the SQL and the rendering, not Citus itself)', () => {
    test('with readable metadata: tables are flagged and coordinator numbers are withheld', async () => {
        const citus = new PGlite();
        await citus.exec(FIXTURE.replace(/do \$\$[\s\S]*?end \$\$;/, ''));
        await citus.exec(CITUS_FAKE);
        const saved = pg;
        pg = citus;
        try {
            const ctx = makeCtx();
            const caps = await import('../src/capabilities.js').then((m) => m.getCapabilities(ctx));
            ctx.cache.set('capabilities', { ...caps.value, citus: true, citus_version: '12.1-1', citus_metadata_readable: true });

            const info = await call(ctx, 'connection_info');
            assert.match(info.text, /citus {7}12\.1-1 · distributed 1 · append\/range 0 · reference 1 · local 0/);
            assert.match(info.text, /Distributed \/ reference tables exist/);

            const ov = await call(ctx, 'schema_overview', { pattern: 'freight_unit' });
            assert.match(ov.text, /portal\.freight_unit\s+table\s+\?\s+\?\s+.*citus: distributed/);
            assert.match(ov.text, /portal_dev\.freight_unit\s+table\s+0/);

            const d = await call(ctx, 'describe_table', { tables: ['portal.freight_unit', 'portal.purchase_order_company'] });
            assert.match(d.text, /citus: distributed on \(id\) · 32 shards · colocation 7/);
            assert.match(d.text, /citus: reference/);
            assert.match(d.text, /est rows \?/);
            assert.ok(d.queries <= 3);
        } finally {
            pg = saved;
            await citus.close();
        }
    });

    test('metadata promised but not usable: falls back to the plain query and says so', async () => {
        const ctx = makeCtx();
        const caps = await import('../src/capabilities.js').then((m) => m.getCapabilities(ctx));
        ctx.cache.set('capabilities', { ...caps.value, citus: true, citus_version: '12.1-1', citus_metadata_readable: true });
        const ov = await call(ctx, 'schema_overview', { pattern: 'focus__*' });
        assert.equal(ov.isError, false, ov.text);
        assert.match(ov.text, /Citus metadata query failed .*Fell back to the plain catalog query/);
        assert.match(ov.text, /public\.focus__shipments\s+table\s+300/);
    });
});

describe('small pure helpers', () => {
    test('parseRelationName', () => {
        assert.deepEqual(parseRelationName('portal.freight_unit'), { schema: 'portal', name: 'freight_unit' });
        assert.deepEqual(parseRelationName('portal."PurchaseOrderLine"'), { schema: 'portal', name: 'PurchaseOrderLine' });
        assert.deepEqual(parseRelationName('Portal.Freight_Unit'), { schema: 'portal', name: 'freight_unit' });
        assert.deepEqual(parseRelationName('"Weird.Name"'), { schema: null, name: 'Weird.Name' });
        assert.deepEqual(parseRelationName('"a""b"'), { schema: null, name: 'a"b' });
        assert.deepEqual(parseRelationName('  sql_source  '), { schema: null, name: 'sql_source' });
        assert.ok(parseRelationName('portal.').error);
        assert.ok(parseRelationName('').error);
        assert.ok(parseRelationName('a b').error);
    });
    test('familyOf', () => {
        assert.equal(familyOf('focus__shipments'), 'focus__');
        assert.equal(familyOf('dax__dim__date'), 'dax__');
        assert.equal(familyOf('analytical_x__y'), 'analytical_x__');
        assert.equal(familyOf('sql_source'), null);
        assert.equal(familyOf('__fx'), null);
    });
});
