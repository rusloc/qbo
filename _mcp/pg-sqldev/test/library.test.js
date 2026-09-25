// @ts-check
/**
 * False-positive guard: every report query mirrored in __DATA/_SRC/_SQL must classify as an
 * allowed read-only statement. These are the statements explain_query / run_query will be fed in
 * increment 2, so a classifier rule that refuses one of them is a bug in the rule.
 * Reads local files only. Skipped when the library folder is not there.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { classify } from '../src/classify.js';

const LIBRARY = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '__DATA', '_SRC', '_SQL');

/**
 * Body of the deploy wrapper:  set dev.x = $sql$ ... $sql$   (closing semicolon optional in this repo).
 * @param {string} text
 */
function unwrap(text) {
    const open = text.indexOf('$sql$');
    const close = text.lastIndexOf('$sql$');
    return open !== -1 && close > open ? text.slice(open + 5, close) : null;
}

describe('the mirrored SQL library', { skip: !fs.existsSync(LIBRARY) && 'library folder not found' }, () => {
    const files = fs.existsSync(LIBRARY) ? fs.readdirSync(LIBRARY).filter((f) => f.toLowerCase().endsWith('.sql')) : [];

    test('there is a library to check', () => assert.ok(files.length >= 30, `found ${files.length} files`));

    for (const file of files) {
        const text = fs.readFileSync(path.join(LIBRARY, file), 'utf8');
        const body = unwrap(text);
        if (body === null) continue; // snippet templates without a deploy wrapper
        test(`${file}: the query body is accepted`, () => {
            const verdict = classify(body);
            assert.equal(verdict.ok, true, verdict.ok ? '' : verdict.reason);
        });
        test(`${file}: the whole deploy file is refused (it is a SET plus an UPDATE)`, () => {
            assert.equal(classify(text).ok, false);
        });
    }
});
