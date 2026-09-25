// @ts-check
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createCache } from '../src/cache.js';

const tmpFile = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'pg-sqldev-cache-')), 'snap.json');

describe('ttl cache', () => {
    test('a repeated call issues zero loads', async () => {
        const cache = createCache({ ttlMs: 60_000, identity: 'a' });
        let loads = 0;
        const loader = async () => {
            loads += 1;
            return { n: loads };
        };
        const first = await cache.getOrLoad('k', loader);
        const second = await cache.getOrLoad('k', loader);
        const third = await cache.getOrLoad('k', loader);
        assert.equal(loads, 1);
        assert.equal(first.cached, false);
        assert.equal(second.cached, true);
        assert.deepEqual(third.value, { n: 1 });
    });

    test('refresh bypasses the cache and overwrites it', async () => {
        const cache = createCache({ ttlMs: 60_000, identity: 'a' });
        let loads = 0;
        const loader = async () => ++loads;
        await cache.getOrLoad('k', loader);
        const refreshed = await cache.getOrLoad('k', loader, { refresh: true });
        const after = await cache.getOrLoad('k', loader);
        assert.equal(refreshed.cached, false);
        assert.equal(refreshed.value, 2);
        assert.equal(after.cached, true);
        assert.equal(after.value, 2);
        assert.equal(loads, 2);
    });

    test('entries expire after the ttl', async () => {
        let t = 1_000_000;
        const cache = createCache({ ttlMs: 10_000, identity: 'a', now: () => t });
        let loads = 0;
        const loader = async () => ++loads;
        await cache.getOrLoad('k', loader);
        t += 9_999;
        assert.equal((await cache.getOrLoad('k', loader)).cached, true);
        t += 2;
        assert.equal((await cache.getOrLoad('k', loader)).cached, false);
        assert.equal(loads, 2);
    });

    test('age is reported', async () => {
        let t = 0;
        const cache = createCache({ ttlMs: 60_000, identity: 'a', now: () => t });
        await cache.getOrLoad('k', async () => 1);
        t += 42_000;
        assert.equal((await cache.getOrLoad('k', async () => 2)).ageMs, 42_000);
    });

    test('concurrent loads of one key share a single load', async () => {
        const cache = createCache({ ttlMs: 60_000, identity: 'a' });
        let loads = 0;
        const loader = () =>
            new Promise((resolve) => {
                loads += 1;
                setTimeout(() => resolve('v'), 20);
            });
        const results = await Promise.all([cache.getOrLoad('k', loader), cache.getOrLoad('k', loader), cache.getOrLoad('k', loader)]);
        assert.equal(loads, 1);
        assert.deepEqual(results.map((r) => r.value), ['v', 'v', 'v']);
    });

    test('a failed load is not cached and the next call retries', async () => {
        const cache = createCache({ ttlMs: 60_000, identity: 'a' });
        let loads = 0;
        const loader = async () => {
            loads += 1;
            if (loads === 1) throw new Error('boom');
            return 'ok';
        };
        await assert.rejects(cache.getOrLoad('k', loader), /boom/);
        assert.equal((await cache.getOrLoad('k', loader)).value, 'ok');
        assert.equal(loads, 2);
    });

    test('ttl 0 disables caching', async () => {
        const cache = createCache({ ttlMs: 0, identity: 'a' });
        let loads = 0;
        await cache.getOrLoad('k', async () => ++loads);
        await cache.getOrLoad('k', async () => ++loads);
        assert.equal(loads, 2);
        assert.equal(cache.info().enabled, false);
    });

    test('clear by prefix', async () => {
        const cache = createCache({ ttlMs: 60_000, identity: 'a' });
        cache.set('describe:a', 1);
        cache.set('describe:b', 2);
        cache.set('overview', 3);
        cache.clear('describe:');
        assert.equal(cache.get('describe:a'), undefined);
        assert.equal(cache.get('overview')?.value, 3);
    });
});

describe('disk snapshot', () => {
    test('a new process starts warm from the snapshot', async () => {
        const file = tmpFile();
        const a = createCache({ ttlMs: 60_000, identity: 'db1', snapshotFile: file });
        await a.getOrLoad('overview', async () => ({ relations: 12 }));

        const b = createCache({ ttlMs: 60_000, identity: 'db1', snapshotFile: file });
        let loads = 0;
        const r = await b.getOrLoad('overview', async () => {
            loads += 1;
            return { relations: -1 };
        });
        assert.equal(loads, 0, 'served from the snapshot, no load');
        assert.equal(r.cached, true);
        assert.deepEqual(r.value, { relations: 12 });
        assert.equal(b.info().snapshotLoaded, 1);
    });

    test('a snapshot from another connection target is ignored', async () => {
        const file = tmpFile();
        const a = createCache({ ttlMs: 60_000, identity: 'db1', snapshotFile: file });
        a.set('overview', 'from db1');
        const b = createCache({ ttlMs: 60_000, identity: 'db2', snapshotFile: file });
        assert.equal(b.get('overview'), undefined);
    });

    test('expired snapshot entries are not loaded', async () => {
        const file = tmpFile();
        let t = 0;
        const a = createCache({ ttlMs: 10_000, identity: 'db1', snapshotFile: file, now: () => t });
        a.set('k', 1);
        t += 10_001;
        const b = createCache({ ttlMs: 10_000, identity: 'db1', snapshotFile: file, now: () => t });
        assert.equal(b.get('k'), undefined);
    });

    test('a corrupt snapshot is survived', () => {
        const file = tmpFile();
        fs.writeFileSync(file, '{ not json');
        const c = createCache({ ttlMs: 60_000, identity: 'db1', snapshotFile: file });
        assert.equal(c.info().snapshotErrors, 1);
        c.set('k', 1);
        assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).entries.k.value, 1, 'and replaced on the next write');
    });

    test('an unwritable snapshot path never fails a call', async () => {
        const dirAsFile = tmpFile();
        fs.writeFileSync(dirAsFile, 'x');
        const c = createCache({ ttlMs: 60_000, identity: 'db1', snapshotFile: path.join(dirAsFile, 'nested', 'snap.json') });
        const r = await c.getOrLoad('k', async () => 'still works');
        assert.equal(r.value, 'still works');
        assert.ok(c.info().snapshotErrors >= 1);
    });

    test('no temp files are left behind', async () => {
        const file = tmpFile();
        const c = createCache({ ttlMs: 60_000, identity: 'db1', snapshotFile: file });
        c.set('a', 1);
        c.set('b', 2);
        assert.deepEqual(fs.readdirSync(path.dirname(file)), ['snap.json']);
    });
});
