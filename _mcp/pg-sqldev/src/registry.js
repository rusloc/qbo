// @ts-check
/**
 * Tool registry. One module per tool under src/tools/. A tool is
 *   { name, title, description, input: <zod raw shape>, handler(ctx, args) -> Promise<string> }
 * Adding a tool = write the module, add it to this list.
 */
import { connectionInfo } from './tools/connection-info.js';
import { schemaOverview } from './tools/schema-overview.js';
import { describeTable } from './tools/describe-table.js';

// Increment 1. Increment 2 (find_columns, join_paths, explain_query, sample_rows, run_query,
// sql_source) and increment 3 are queued on the build board and are added here when built.
export const tools = [connectionInfo, schemaOverview, describeTable];
