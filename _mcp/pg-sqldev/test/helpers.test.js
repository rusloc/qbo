// @ts-check
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadConfig, describeConfig, notReadyMessage } from '../src/config.js';
import { preprocess } from '../src/sql.js';
import { fmtCount, fmtBytes, fmtPct, clip, renderTable, applyBudget, nameMatcher, quoteIdent } from '../src/format.js';

/** @param {string} body */
function envFile(body) {
    const f = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'pg-sqldev-env-')), 'test.env');
    fs.writeFileSync(f, body);
    return f;
}

describe('config', () => {
    test('missing env file: not ready, explains itself, does not throw', () => {
        const c = loadConfig({ envFile: path.join(os.tmpdir(), 'pg-sqldev-definitely-missing.env'), env: {} });
        assert.equal(c.ready, false);
        assert.equal(c.envFileFound, false);
        assert.deepEqual(c.missing, ['PGHOST', 'PGDATABASE', 'PGUSER', 'PGPASSWORD']);
        assert.match(notReadyMessage(c), /\.env\.example/);
    });

    test('complete file: ready, defaults applied', () => {
        const c = loadConfig({ envFile: envFile('PGHOST=h\nPGDATABASE=d\nPGUSER=u\nPGPASSWORD="p#ss word=1"\n'), env: {} });
        assert.equal(c.ready, true);
        assert.equal(c.password, 'p#ss word=1');
        assert.equal(c.port, 5432);
        assert.deepEqual(c.schemas, ['public', 'portal', 'portal_dev']);
        assert.equal(c.statementTimeoutMs, 15_000);
        assert.equal(c.lockTimeoutMs, 2_000);
        assert.equal(c.cacheTtlMs, 600_000);
        assert.equal(c.poolMax, 2);
        assert.deepEqual(c.ssl, { rejectUnauthorized: true });
    });

    test('the file wins over the process environment; the environment only fills gaps', () => {
        const c = loadConfig({
            envFile: envFile('PGHOST=from-file\nPGDATABASE=d\nPGUSER=u\n'),
            env: { PGHOST: 'from-env', PGPASSWORD: 'env-secret' },
        });
        assert.equal(c.host, 'from-file');
        assert.equal(c.password, 'env-secret');
        assert.equal(c.source.PGHOST, 'file');
        assert.equal(c.source.PGPASSWORD, 'env');
        assert.equal(c.ready, true);
    });

    test('the pool can be lowered but never raised above two', () => {
        const base = 'PGHOST=h\nPGDATABASE=d\nPGUSER=u\nPGPASSWORD=p\n';
        assert.equal(loadConfig({ envFile: envFile(`${base}PG_POOL_MAX=50\n`), env: {} }).poolMax, 2);
        assert.equal(loadConfig({ envFile: envFile(`${base}PG_POOL_MAX=1\n`), env: {} }).poolMax, 1);
    });

    test('timeouts are clamped, garbage falls back to the default', () => {
        const base = 'PGHOST=h\nPGDATABASE=d\nPGUSER=u\nPGPASSWORD=p\n';
        assert.equal(loadConfig({ envFile: envFile(`${base}PG_STATEMENT_TIMEOUT_MS=0\n`), env: {} }).statementTimeoutMs, 1_000);
        assert.equal(loadConfig({ envFile: envFile(`${base}PG_STATEMENT_TIMEOUT_MS=99999999\n`), env: {} }).statementTimeoutMs, 120_000);
        assert.equal(loadConfig({ envFile: envFile(`${base}PG_STATEMENT_TIMEOUT_MS=abc\n`), env: {} }).statementTimeoutMs, 15_000);
    });

    test('there is no way to switch TLS verification off', () => {
        const c = loadConfig({
            envFile: envFile('PGHOST=h\nPGDATABASE=d\nPGUSER=u\nPGPASSWORD=p\nPGSSLMODE=disable\nNODE_TLS_REJECT_UNAUTHORIZED=0\n'),
            env: { PGSSLMODE: 'no-verify' },
        });
        assert.equal(c.ssl.rejectUnauthorized, true);
    });

    test('an unreadable CA bundle is a config error, not a silent downgrade', () => {
        const c = loadConfig({ envFile: envFile('PGHOST=h\nPGDATABASE=d\nPGUSER=u\nPGPASSWORD=p\nPGSSLROOTCERT=Z:/nope/ca.pem\n'), env: {} });
        assert.equal(c.ready, false);
        assert.match(c.errors.join(' '), /PGSSLROOTCERT/);
    });

    test('the password never appears in the redacted view, in JSON, or in the not-ready text', () => {
        const c = loadConfig({ envFile: envFile('PGHOST=h\nPGDATABASE=d\nPGUSER=u\nPGPASSWORD=TOPSECRET123\n'), env: {} });
        assert.doesNotMatch(JSON.stringify(describeConfig(c)), /TOPSECRET123/);
        assert.doesNotMatch(JSON.stringify(c), /TOPSECRET123/);
        assert.doesNotMatch(notReadyMessage(c), /TOPSECRET123/);
        assert.equal(describeConfig(c).password, '(set)');
    });

    test('the identity fingerprint follows the target, not the password', () => {
        const a = loadConfig({ envFile: envFile('PGHOST=h\nPGDATABASE=d\nPGUSER=u\nPGPASSWORD=one\n'), env: {} });
        const b = loadConfig({ envFile: envFile('PGHOST=h\nPGDATABASE=d\nPGUSER=u\nPGPASSWORD=two\n'), env: {} });
        const c = loadConfig({ envFile: envFile('PGHOST=other\nPGDATABASE=d\nPGUSER=u\nPGPASSWORD=one\n'), env: {} });
        assert.equal(a.identity, b.identity);
        assert.notEqual(a.identity, c.identity);
    });
});

describe('sql preprocess', () => {
    const src = ['select', '     1 _a', '-- #if citus', '    ,2 _b', '-- #else', '    ,null _b', '-- #endif', 'from t'].join('\n');
    test('flag on', () => assert.equal(preprocess(src, { citus: true }), 'select\n     1 _a\n    ,2 _b\nfrom t'));
    test('flag off', () => assert.equal(preprocess(src, { citus: false }), 'select\n     1 _a\n    ,null _b\nfrom t'));
    test('negated flag', () => assert.equal(preprocess('-- #if !citus\nx\n-- #endif', {}), 'x'));
    test('ordinary comments pass through', () => assert.equal(preprocess('-- plain comment\nselect 1', {}), '-- plain comment\nselect 1'));
    test('CRLF input is handled', () => assert.equal(preprocess('a\r\n-- #if x\r\nb\r\n-- #endif\r\nc', { x: true }), 'a\nb\nc'));
    test('unterminated block throws', () => assert.throws(() => preprocess('-- #if citus\nx', {}), /unterminated/));
    test('nested block throws', () => assert.throws(() => preprocess('-- #if a\n-- #if b\n-- #endif\n-- #endif', {}), /nested/));
    test('stray else throws', () => assert.throws(() => preprocess('-- #else', {}), /without #if/));
});

describe('format', () => {
    test('counts', () => {
        assert.equal(fmtCount(null), '?');
        assert.equal(fmtCount(-1), '?');
        assert.equal(fmtCount(0), '0');
        assert.equal(fmtCount(999), '999');
        assert.equal(fmtCount(1_234), '1.2K');
        assert.equal(fmtCount(56_789), '57K');
        assert.equal(fmtCount(1_234_567), '1.2M');
        assert.equal(fmtCount(2_500_000_000), '2.5B');
    });
    test('bytes', () => {
        assert.equal(fmtBytes(0), '0');
        assert.equal(fmtBytes(8192), '8.0 KB');
        assert.equal(fmtBytes(356_515_840), '340 MB');
        assert.equal(fmtBytes(null), '?');
    });
    test('percent', () => {
        assert.equal(fmtPct(0), '0%');
        assert.equal(fmtPct(0.0004), '<0.1%');
        assert.equal(fmtPct(0.034), '3.4%');
        assert.equal(fmtPct(0.5), '50%');
        assert.equal(fmtPct(null), '');
    });
    test('clip collapses whitespace and cuts', () => {
        assert.equal(clip('a\n  b\tc', 80), 'a b c');
        assert.equal(clip('abcdefghij', 5), 'abcd…');
        assert.equal(clip(null, 5), '');
    });
    test('table: aligned, right-aligned numbers, empty columns dropped', () => {
        const out = renderTable(
            [
                { key: 'name', label: 'name' },
                { key: 'rows', label: 'rows', align: 'right' },
                { key: 'comment', label: 'comment' },
            ],
            [
                { name: 'freight_unit', rows: '1.2M', comment: null },
                { name: 'x', rows: '7', comment: null },
            ],
        );
        assert.equal(out, 'name          rows\nfreight_unit  1.2M\nx                7');
    });
    test('table: no rows', () => assert.equal(renderTable([{ key: 'a', label: 'a' }], []), '(none)'));
    test('budget: under the limit is untouched', () => assert.deepEqual(applyBudget('abc', 1000, 'h'), { text: 'abc', truncated: false }));
    test('budget: over the limit cuts on a line and says so', () => {
        const text = Array.from({ length: 500 }, (_, i) => `line ${i} ${'x'.repeat(40)}`).join('\n');
        const r = applyBudget(text, 4096, 'Narrow with pattern.');
        assert.equal(r.truncated, true);
        assert.ok(Buffer.byteLength(r.text) <= 4096);
        assert.match(r.text, /\[truncated: .* Narrow with pattern\.\]$/);
    });
    test('name matcher', () => {
        assert.equal(nameMatcher(undefined)('anything'), true);
        assert.equal(nameMatcher('freight')('freight_unit_enrich'), true, 'no wildcard = contains');
        assert.equal(nameMatcher('FREIGHT')('freight_unit'), true, 'case-insensitive');
        assert.equal(nameMatcher('focus__*')('focus__shipments'), true);
        assert.equal(nameMatcher('focus__*')('dax__focus__x'), false, 'wildcard patterns are anchored');
        assert.equal(nameMatcher('focus__%')('focus__shipments'), true, 'SQL style wildcard works too');
        assert.equal(nameMatcher('a_c*')('abc'), false, 'underscore is literal');
        assert.equal(nameMatcher('a?c')('abc'), true);
        assert.equal(nameMatcher('a.c*')('abcd'), false, 'regex characters are escaped');
    });
    test('quoteIdent', () => {
        assert.equal(quoteIdent('freight_unit'), 'freight_unit');
        assert.equal(quoteIdent('PurchaseOrderLine'), '"PurchaseOrderLine"');
        assert.equal(quoteIdent('has space'), '"has space"');
        assert.equal(quoteIdent('we"ird'), '"we""ird"');
    });
});
