#!/usr/bin/env node
// @ts-check
/**
 * pg-sqldev: local, read-only MCP server over stdio.
 *
 * stdout carries the JSON-RPC stream and nothing else. Every diagnostic goes to stderr.
 * No port is opened. The process ends when the client closes stdin.
 */
import path from 'node:path';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { loadConfig } from './config.js';
import { createDb } from './db.js';
import { createCache } from './cache.js';
import { buildServer, VERSION } from './server.js';

// A stray console.log from any dependency would corrupt the protocol stream. Send it to stderr.
console.log = console.error;
console.info = console.error;
console.debug = console.error;

const config = loadConfig();
const db = createDb(config);
const cache = createCache({
    ttlMs: config.cacheTtlMs,
    identity: config.identity,
    snapshotFile: path.join(config.cacheDir, 'catalog-snapshot.json'),
});
const ctx = { config, db, cache, version: VERSION };

const server = buildServer(ctx);
const transport = new StdioServerTransport();

let closing = false;
/** @param {string} why */
async function shutdown(why) {
    if (closing) return;
    closing = true;
    console.error(`[pg-sqldev] shutting down (${why})`);
    try {
        await db.end();
    } catch {
        /* the pool is going away anyway */
    }
    process.exit(0);
}

transport.onclose = () => void shutdown('transport closed');
process.stdin.on('end', () => void shutdown('stdin ended'));
process.on('SIGINT', () => void shutdown('SIGINT'));
process.on('SIGTERM', () => void shutdown('SIGTERM'));
process.on('unhandledRejection', (reason) => {
    console.error(`[pg-sqldev] unhandled rejection: ${reason instanceof Error ? reason.message : String(reason)}`);
});

await server.connect(transport);
console.error(
    `[pg-sqldev] ${VERSION} ready on stdio · ${config.ready ? `target ${config.database}@${config.host}:${config.port} as ${config.user}` : `NOT CONFIGURED (${config.envFileFound ? `missing ${config.missing.join(', ')}` : `no ${config.envFile}`})`}`,
);
