// @ts-check
/**
 * Builds the MCP server from the registry. Kept apart from index.js so tests can drive the same
 * tool pipeline (validation, not-configured handling, error mapping) without a stdio transport.
 */
import fs from 'node:fs';
import path from 'node:path';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { SERVER_DIR, notReadyMessage } from './config.js';
import { explainDbError, NotConfiguredError, RefusedError } from './db.js';
import { tools } from './registry.js';

export const VERSION = JSON.parse(fs.readFileSync(path.join(SERVER_DIR, 'package.json'), 'utf8')).version;

const INSTRUCTIONS = [
    'pg-sqldev gives read-only catalog facts about the configured PostgreSQL database so that analytical SQL can be written correctly and cheaply.',
    'Order of use: connection_info once per session, schema_overview to map, describe_table for the tables you will join.',
    'All tools read system catalogs and statistics views only. Row counts and sizes are estimates. Results are cached for 10 minutes; pass refresh: true to re-read.',
    'Quoted mixed-case names must be written exactly, e.g. portal."PurchaseOrderLine".',
].join(' ');

/**
 * Run one tool call and shape the MCP result. Never throws.
 * @param {import('./capabilities.js').Ctx} ctx
 * @param {{ name: string, handler: (ctx: any, args: any) => Promise<string> }} tool
 * @param {any} args
 */
export async function runTool(ctx, tool, args) {
    if (!ctx.config.ready && !ctx.db.injected) {
        return { isError: true, content: [{ type: /** @type {const} */ ('text'), text: notReadyMessage(ctx.config) }] };
    }
    try {
        const text = await tool.handler(ctx, args ?? {});
        return { content: [{ type: /** @type {const} */ ('text'), text }] };
    } catch (e) {
        let text;
        if (e instanceof NotConfiguredError) text = notReadyMessage(ctx.config);
        else if (e instanceof RefusedError) text = e.message;
        else if (/** @type {{ code?: string }} */ (e).code || /timeout|ECONN|certificate/i.test(String(/** @type {Error} */ (e).message))) text = `${tool.name} failed: ${explainDbError(e)}`;
        else text = `${tool.name} failed: ${/** @type {Error} */ (e).message}`;
        console.error(`[pg-sqldev] ${text.split('\n')[0]}`);
        return { isError: true, content: [{ type: /** @type {const} */ ('text'), text }] };
    }
}

/** @param {import('./capabilities.js').Ctx} ctx */
export function buildServer(ctx) {
    const server = new McpServer({ name: 'pg-sqldev', version: VERSION }, { instructions: INSTRUCTIONS });
    for (const tool of tools) {
        server.registerTool(
            tool.name,
            {
                title: tool.title,
                description: tool.description,
                inputSchema: tool.input,
                annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
            },
            async (/** @type {any} */ args) => runTool(ctx, tool, args),
        );
    }
    return server;
}
