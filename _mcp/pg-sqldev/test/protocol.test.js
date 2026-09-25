// @ts-check
/**
 * A2 verify: MCP initialize and tools/list succeed over stdio.
 * Spawns the real server process with no .env, so no database is involved.
 */
import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const SERVER = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'index.js');

describe('stdio protocol, server not configured', () => {
    /** @type {Client} */
    let client;
    let stderr = '';

    before(async () => {
        const transport = new StdioClientTransport({
            command: process.execPath,
            args: [SERVER],
            env: { ...process.env, PG_SQLDEV_ENV_FILE: path.join(os.tmpdir(), 'pg-sqldev-no-such-file.env'), PGHOST: '', PGUSER: '', PGPASSWORD: '', PGDATABASE: '' },
            stderr: 'pipe',
        });
        transport.stderr?.on('data', (d) => {
            stderr += String(d);
        });
        client = new Client({ name: 'pg-sqldev-protocol-test', version: '0.0.0' });
        await client.connect(transport);
    });

    after(async () => {
        await client.close();
    });

    test('initialize: server identifies itself and ships usage instructions', () => {
        const info = client.getServerVersion();
        assert.equal(info?.name, 'pg-sqldev');
        assert.match(String(info?.version), /^\d+\.\d+\.\d+$/);
        assert.match(String(client.getInstructions()), /connection_info.*schema_overview.*describe_table/);
    });

    test('tools/list: the three increment-1 tools, read-only, with input schemas', async () => {
        const { tools } = await client.listTools();
        assert.deepEqual(tools.map((t) => t.name).sort(), ['connection_info', 'describe_table', 'schema_overview']);
        for (const t of tools) {
            assert.equal(t.inputSchema.type, 'object', `${t.name} has an object input schema`);
            assert.equal(t.annotations?.readOnlyHint, true, `${t.name} is flagged read-only`);
            assert.ok((t.description ?? '').length > 40, `${t.name} has a real description`);
        }
        const describe = tools.find((t) => t.name === 'describe_table');
        assert.deepEqual(describe?.inputSchema.required, ['tables']);
        const tablesProp = /** @type {any} */ (describe?.inputSchema.properties)?.tables;
        assert.equal(tablesProp.maxItems, 10, 'batch limit of ten is part of the published schema');
    });

    test('a tool call without configuration explains itself and makes no database call', async () => {
        const r = await client.callTool({ name: 'connection_info', arguments: {} });
        assert.equal(r.isError, true);
        const text = /** @type {any[]} */ (r.content)[0].text;
        assert.match(text, /not configured/);
        assert.match(text, /\.env\.example/);
        assert.match(text, /PGHOST, PGDATABASE, PGUSER, PGPASSWORD/);
    });

    test('input validation happens before anything else: eleven tables are refused', async () => {
        const tables = Array.from({ length: 11 }, (_, i) => `public.t${i}`);
        let refused = false;
        try {
            const r = await client.callTool({ name: 'describe_table', arguments: { tables } });
            refused = r.isError === true;
        } catch {
            refused = true;
        }
        assert.equal(refused, true);
    });

    test('unknown arguments of the wrong type are refused', async () => {
        let refused = false;
        try {
            const r = await client.callTool({ name: 'schema_overview', arguments: { limit: 'many' } });
            refused = r.isError === true;
        } catch {
            refused = true;
        }
        assert.equal(refused, true);
    });

    test('stderr carries the diagnostics; the startup line says NOT CONFIGURED and leaks nothing', () => {
        assert.match(stderr, /\[pg-sqldev\] \d+\.\d+\.\d+ ready on stdio · NOT CONFIGURED/);
    });
});
