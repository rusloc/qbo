// @ts-check
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { classify, tokenize } from '../src/classify.js';

/** @param {string} sql @param {{ allowAnalyze?: boolean }} [o] */
const ok = (sql, o) => {
    const r = classify(sql, o);
    assert.equal(r.ok, true, `expected ACCEPT but got: ${r.ok ? '' : r.reason}\n  sql: ${sql}`);
    return /** @type {Extract<ReturnType<typeof classify>, { ok: true }>} */ (r);
};
/** @param {string} sql @param {RegExp} [why] @param {{ allowAnalyze?: boolean }} [o] */
const no = (sql, why, o) => {
    const r = classify(sql, o);
    assert.equal(r.ok, false, `expected REFUSE but it was accepted\n  sql: ${sql}`);
    if (why && !r.ok) assert.match(r.reason, why, `wrong reason for: ${sql}`);
};

describe('accepts the six allowed keywords', () => {
    test('select', () => assert.equal(ok('select 1').keyword, 'select'));
    test('with', () => assert.equal(ok('with a as (select 1) select * from a').keyword, 'with'));
    test('values', () => assert.equal(ok('values (1), (2)').keyword, 'values'));
    test('table', () => assert.equal(ok('table public.sql_source').keyword, 'table'));
    test('explain', () => assert.equal(ok('explain select 1').keyword, 'explain'));
    test('show', () => assert.equal(ok('show server_version').keyword, 'show'));
    test('case and whitespace do not matter', () => ok('  \n\t SeLeCt 1'));
    test('trailing semicolons are fine', () => ok('select 1 ;; \n -- done\n'));
    test('parenthesised select', () => ok('(select 1) union all (select 2)'));
});

describe('refuses everything that is not read-only', () => {
    for (const sql of [
        'insert into t values (1)',
        "update sql_source set _code = 'x'",
        'delete from t',
        'merge into t using s on true when matched then delete',
        'truncate t',
        'create table t (id int)',
        'alter table t add column c int',
        'drop table t',
        'create index on t (id)',
        'grant select on t to public',
        'refresh materialized view portal.tracker',
        'vacuum t',
        'analyze t',
        'reindex table t',
        'cluster t',
        "set statement_timeout = '0'",
        'set default_transaction_read_only = off',
        'reset all',
        'do $$ begin delete from t; end $$',
        'call some_procedure()',
        "copy t to '/tmp/x'",
        'copy (select 1) to stdout',
        'begin',
        'commit',
        'rollback',
        'start transaction read write',
        'lock table t',
        'listen ch',
        'notify ch',
        'prepare p as select 1',
        'execute p',
        'declare c cursor for select 1',
        'fetch all from c',
        'discard all',
        'comment on table t is $$x$$',
        "security label on table t is 'x'",
        'import foreign schema s from server x into public',
    ]) {
        test(sql.slice(0, 50), () => no(sql, /not allowed/));
    }
});

describe('single statement only', () => {
    test('stacked statements', () => no('select 1; drop table t', /multiple statements/));
    test('stacked after a comment', () => no('select 1; /* x */ delete from t', /multiple statements/));
    test('stacked selects are refused too', () => no('select 1; select 2', /multiple statements/));
    test('semicolon inside a string is data', () => ok("select ';' , 'a;b'"));
    test('semicolon inside a quoted identifier is data', () => ok('select 1 "a;b"'));
    test('semicolon inside a line comment is ignored', () => ok('select 1 -- ; drop table t'));
    test('semicolon inside a block comment is ignored', () => ok('select 1 /* ; drop table t */'));
    test('semicolon inside a dollar quote is data', () => ok('select $sql$ a; b $sql$'));
});

describe('comments', () => {
    test('leading line comments', () => ok('-- header\n-- more\nselect 1'));
    test('leading block comment', () => ok('/* header */ select 1'));
    test('nested block comments', () => ok('/* a /* b */ still comment */ select 1'));
    test('a comment cannot smuggle the first keyword', () => no('/* select */ delete from t', /not allowed/));
    test('a line comment cannot smuggle the first keyword', () => no('-- select\ndelete from t', /not allowed/));
    test('unterminated block comment', () => no('select 1 /* open', /unterminated block comment/));
    test('comments only', () => no('-- nothing here', /empty statement/));
    test('empty input', () => no('   ', /empty statement/));
});

describe('string literals', () => {
    test("doubled quote ''", () => ok("select 'it''s; fine'"));
    test('unterminated string', () => no("select 'open", /unterminated string/));
    test('standard string: backslash is NOT an escape', () => {
        // The string is  \  and ends at the second quote. What follows is a second statement.
        no("select '\\'; delete from t; --'", /multiple statements/);
    });
    test("E'' string: backslash IS an escape", () => {
        // Here \' stays inside the string, so the whole tail is one literal.
        ok("select E'\\'; delete from t; --'");
    });
    test("E'' detection does not misfire on identifiers ending in e", () => {
        no("select name'\\'; delete from t; --'", /multiple statements/);
    });
    test('keywords inside strings are data', () => ok("select 'delete from t', 'insert'"));
});

describe('dollar quotes', () => {
    test('$sql$ block with quotes and semicolons inside', () => ok("select length($sql$ select 'x'; update t set a = 1; $sql$)"));
    test('$$ block', () => ok('select $$ a; b $$'));
    test('different tags do not close each other', () => ok('select $a$ text $b$ ; drop $b$ more $a$'));
    test('unterminated dollar quote', () => no('select $sql$ open', /unterminated dollar quote/));
    test('$1 is a parameter, not a dollar quote', () => {
        const { tokens } = tokenize('select $1, $2');
        assert.deepEqual(tokens.filter((t) => t.t === 'param').map((t) => t.v), ['$1', '$2']);
    });
    test('identifier with $ inside is one word', () => {
        const { tokens } = tokenize('select foo$bar$baz from t');
        assert.ok(tokens.some((t) => t.t === 'word' && t.v === 'foo$bar$baz'));
    });
    test('the deploy wrapper itself is refused (it is a SET)', () => no('set dev.ek_view =\n$sql$\nselect 1\n$sql$;', /not allowed/));
});

describe('explain', () => {
    test('plain explain', () => assert.deepEqual(ok('explain select 1').explain, { analyze: false, inner: 'select' }));
    test('explain with options', () => ok('explain (format json, costs off) with a as (select 1) select * from a'));
    test('explain verbose', () => ok('explain verbose select 1'));
    test('explain analyze is refused by default', () => no('explain analyze select 1', /opt-in/));
    test('explain (analyze) is refused by default', () => no('explain (analyze, buffers) select 1', /opt-in/));
    test('explain (costs off, analyze) is refused by default', () => no('explain (costs off, analyze) select 1', /opt-in/));
    test('explain (analyze false) is fine', () => assert.equal(ok('explain (analyze false) select 1').explain?.analyze, false));
    test('explain (analyze off) is fine', () => ok('explain (analyze off, verbose) select 1'));
    test('explain analyze with the opt-in', () => assert.equal(ok('explain analyze select 1', { allowAnalyze: true }).explain?.analyze, true));
    test('explain analyze of DML is refused even with the opt-in', () => no('explain analyze delete from t', /not allowed/, { allowAnalyze: true }));
    test('explain of DML is refused', () => no('explain update t set a = 1', /not allowed/));
    test('explain (analyze) of insert is refused', () => no('explain (analyze) insert into t values (1)', /not allowed/, { allowAnalyze: true }));
    test('explain execute is refused', () => no('explain execute p', /not allowed/));
    test('explain create table as is refused', () => no('explain create table x as select 1', /not allowed/));
    test('explain of a parenthesised select', () => ok('explain (select 1)'));
});

describe('data-modifying CTEs', () => {
    test('delete in a CTE', () => no('with gone as (delete from t returning *) select * from gone', /data-modifying/));
    test('insert in a CTE', () => no('with x as ( insert into t values (1) returning id ) select * from x', /data-modifying/));
    test('update in a materialized CTE', () => no('with x as materialized (update t set a = 1 returning *) select * from x', /data-modifying/));
    test('merge in a CTE', () => no('with x as (merge into t using s on true when matched then delete returning *) select 1', /data-modifying/));
    test('a column called _updated is fine', () => ok('select s._updated, s._code from public.sql_source s'));
    test('words like update in strings are fine', () => ok("select '(delete from t)'"));
});

describe('functions whose effects escape a read-only transaction', () => {
    for (const fn of [
        "set_config('default_transaction_read_only', 'off', false)",
        'pg_catalog.set_config($$a$$, $$b$$, false)',
        '"set_config"(\'a\', \'b\', false)',
        'SET_CONFIG (\'a\', \'b\', false)',
        'pg_terminate_backend(123)',
        'pg_cancel_backend(123)',
        'pg_sleep(600)',
        'pg_advisory_lock(1)',
        'pg_try_advisory_lock(1)',
        "dblink_exec('host=x', 'drop table t')",
        "dblink('host=x', 'select 1')",
        "run_command_on_workers($cmd$ drop table t $cmd$)",
        "run_command_on_shards('t', $cmd$ delete from %s $cmd$)",
        "citus_add_node('x', 5432)",
        "master_remove_node('x', 5432)",
        "create_distributed_table('t', 'id')",
        "nextval('s')",
        "setval('s', 1)",
        "lo_import('/etc/passwd')",
        "pg_read_file('postgresql.conf')",
        'pg_stat_statements_reset()',
        'pg_stat_reset()',
    ]) {
        test(fn.slice(0, 40), () => no(`select ${fn}`, /is not allowed/));
    }
    test('denied name is caught inside a CTE', () => no("with a as (select set_config('x','y',false)) select * from a", /is not allowed/));
    test('read-only citus helpers stay allowed', () => ok("select citus_version(), citus_table_size('t')"));
    test('a denied name inside a string is data', () => ok("select 'pg_sleep(10)'"));
    test('a column merely named like a function is fine', () => ok('select t.nextval from t'));
    test('ordinary functions are fine', () => ok("select count(*), coalesce(a, 0), string_agg(b, ',') from t group by a"));
});

describe('adversarial review 2026-09-18: every finding stays fixed', () => {
    describe('H1: U& unicode escapes are decoded by PostgreSQL before name resolution', () => {
        for (const sql of [
            'select U&"pg\\005fsleep"(0)',
            'select U&"pg\\005fterminate\\005fbackend"(123)',
            "select U&\"run\\005fcommand\\005fon\\005fworkers\"('drop table t')",
            "select U&\"\\006eextval\"('s')",
            "select U&\"\\0064blink\\005fexec\"('host=x', 'drop table t')",
            "select U&\"set\\005fconfig\"('a', 'b', false)",
            'select u&"pg_sleep"(1)',
            "select U&'\\0041' ",
            'select 1 from t where t."x" = 1 and U&"d!0061t" UESCAPE \'!\' = 1',
        ]) {
            test(sql.slice(0, 48), () => no(sql, /U&/));
        }
        test('a column called u next to an ampersand with spaces is not a U& literal', () => ok("select t.u & 1, t.u & '1'::int from t"));
    });

    describe('H2 / M3 / M4: side effects a rollback does not undo, and server file listings', () => {
        for (const fn of [
            "pg_logical_slot_get_changes('slot', null, null)",
            "pg_logical_emit_message(true, 'a', 'b')",
            "pg_file_write('x', 'data', false)",
            "pg_file_unlink('x')",
            "pg_backup_start('label')",
            'pg_backup_stop()',
            "pg_start_backup('label')",
            'pg_wal_replay_pause()',
            'pg_wal_replay_resume()',
            "pg_prewarm('t')",
            'pg_buffercache_evict(1)',
            'pg_ls_waldir()',
            'pg_ls_logdir()',
            "pg_ls_dir('.')",
            'pg_export_snapshot()',
            'txid_current()',
            'pg_current_xact_id()',
            "pg_create_restore_point('x')",
            'pg_stat_reset_shared()',
            "pg_sleep_for('5 minutes')",
        ]) {
            test(fn.slice(0, 40), () => no(`select ${fn}`, /is not allowed/));
        }
    });

    describe('functions that execute SQL passed as a string can hide a denied call', () => {
        for (const fn of [
            "query_to_xml('select pg_terminate_backend(123)', true, true, '')",
            "query_to_xml_and_xmlschema('select 1', true, true, '')",
            "table_to_xml('portal.freight_unit', true, true, '')",
            "ts_stat('select pg_sleep(100)::text::tsvector')",
            "crosstab('select 1, 2, 3')",
            "crosstab2('select 1, 2, 3')",
            "dblink_connect('x', 'host=y')",
        ]) {
            test(fn.slice(0, 40), () => no(`select * from ${fn}`, /is not allowed/));
        }
        test('schema-qualified job schedulers', () => no("select cron.schedule('j', '* * * * *', 'delete from t')", /schema "cron"/));
        test('schema-qualified, quoted', () => no('select "cron"."schedule"(\'j\', \'* * * * *\', \'vacuum\')', /schema "cron"/));
    });

    describe('M1: a write behind an allowed first keyword, in every shape', () => {
        test('top-level delete after a CTE list', () => no('with x as (select 1) delete from t', /data-modifying/));
        test('top-level insert after a CTE list', () => no('with x as (select 1) insert into t select * from x', /data-modifying/));
        test('top-level update after a CTE list', () => no('with x as (select 1) update t set a = 1', /data-modifying/));
        test('top-level merge after a CTE list', () => no('with x as (select 1) merge into t using x on true when matched then delete', /data-modifying/));
        test('nested: a CTE whose body is itself with ... delete', () => no('with x as (with y as (select 1) delete from t returning *) select * from x', /data-modifying/));
        test('behind a recursive CTE with a search clause', () =>
            no('with recursive r as (select 1 id union all select id + 1 from r where id < 3) search depth first by id set o delete from t', /data-modifying/));
        test('row locks: select ... for update', () => no('select * from t for update', /locking keyword "update"/));
        test('row locks: for no key update', () => no('select * from t for no key update skip locked', /locking keyword "update"/));
        test('a column with such a name works qualified', () => ok('select t.update, t.delete, t."insert" from t'));
        test('a column with such a name works quoted', () => ok('with x ("merge") as (select 1) select x."merge", "update" from x'));
        test('a bare column with such a name is refused, and the message says what to do', () => no('with x (merge) as (select 1) select * from x', /quote it/));
        test('house-style names that merely contain the words are fine', () => ok('select s._updated, s._delete_flag, s.insert_ts, s.updated_at, s.merge_key from public.sql_source s'));
    });

    describe('M2 / L3: the tokenizer uses PostgreSQL line endings and whitespace, not JavaScript ones', () => {
        test('a bare CR ends a line comment, so the hidden second statement is seen', () => no('select 1 --\r; drop table t_demo', /multiple statements/));
        test('CRLF line comments', () => ok('select 1 -- note\r\n, 2 -- other\r\n'));
        test('a CR comment cannot hide a denied function', () => no('select 1 --\r, pg_sleep(100)', /is not allowed/));
        test('BOM is not whitespace for PostgreSQL', () => no('\uFEFFselect 1', /not allowed/));
        test('NBSP is not whitespace for PostgreSQL', () => no('\u00A0select 1', /not allowed/));
        test('U+2028 does not end a line comment', () => ok('select 1 -- x\u2028; drop table t'));
        test('form feed and vertical tab are whitespace', () => ok('\f\vselect\f1'));
    });

    describe('L2: ordinary words that happen to start like Citus namespaces', () => {
        test('user functions and CTEs named master_ / worker_ are fine', () =>
            ok('with master_carrier (id, name) as (select 1, 2) select master_carrier_lookup(m.id), worker_count(1) from master_carrier m'));
        test('the real Citus verbs are still refused', () => {
            no("select master_run_on_worker(array['w'], array[5432], array['drop table t'], false)", /is not allowed/);
            no("select master_add_node('w', 5432)", /is not allowed/);
            no("select master_move_shard_placement(1, 'a', 1, 'b', 2)", /is not allowed/);
            no("select worker_apply_shard_ddl_command(1, 'drop table t')", /is not allowed/);
            no("select worker_save_query_explain_analyze('delete from t', '{}')", /is not allowed/);
            no("select create_distributed_table('t', 'id')", /is not allowed/);
            no("select undistribute_table('t')", /is not allowed/);
            no("select rebalance_table_shards('t')", /is not allowed/);
        });
    });

    test('performance: a 1 MB statement classifies in well under a second', () => {
        const big = `select ${Array.from({ length: 60_000 }, (_, i) => `'v${i}' _c${i}`).join(', ')}`;
        assert.ok(big.length > 1_000_000);
        const t0 = Date.now();
        ok(big);
        assert.ok(Date.now() - t0 < 1500, `took ${Date.now() - t0} ms`);
    });
});

describe('real statements from this repo style', () => {
    test('house style select with lateral, jsonb and distinct on', () =>
        ok(`
            with _main as (
                select distinct on (f.id)
                     f.serial_no                                          _serial_no
                    ,e._ship_response ->> 'origin_country'                _origin_country_code
                    ,(select l ->> 'value'
                      from jsonb_array_elements(e._ship_response::jsonb -> 'custom_dates') l
                      where l ->> 'name' = 'Cargo Ready Date Actual')::date   _crd_actual
                from portal.freight_unit f
                left join portal."PurchaseOrderLine" p on p.id = f.id
                where 1=1
                    and f.id is not null
            )
            select * from _main m;
        `));
    test('statement text is returned without the trailing semicolon', () => {
        assert.equal(ok('select 1 ;').statement.trim(), 'select 1');
    });
    test('NUL byte is refused', () => no('select 1 ; drop table t', /NUL/));
});
