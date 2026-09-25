// @ts-check
/** Output helpers: compact text tables, human numbers, size budgets. */

/** @param {number | null | undefined} n */
export function fmtCount(n) {
    if (n === null || n === undefined || Number.isNaN(n) || n < 0) return '?';
    if (n < 1_000) return String(Math.round(n));
    if (n < 1_000_000) return `${(n / 1_000).toFixed(n < 10_000 ? 1 : 0)}K`;
    if (n < 1_000_000_000) return `${(n / 1_000_000).toFixed(n < 10_000_000 ? 1 : 0)}M`;
    return `${(n / 1_000_000_000).toFixed(1)}B`;
}

/** @param {number | null | undefined} bytes */
export function fmtBytes(bytes) {
    if (bytes === null || bytes === undefined || Number.isNaN(bytes) || bytes < 0) return '?';
    if (bytes === 0) return '0';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    let v = bytes;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i += 1;
    }
    return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

/** @param {number | null | undefined} frac */
export function fmtPct(frac) {
    if (frac === null || frac === undefined || Number.isNaN(frac)) return '';
    if (frac === 0) return '0%';
    const p = frac * 100;
    if (p < 0.1) return '<0.1%';
    return `${p < 10 ? p.toFixed(1) : Math.round(p)}%`;
}

/**
 * Collapse whitespace and cut to `max` characters.
 * @param {unknown} value
 * @param {number} max
 */
export function clip(value, max) {
    if (value === null || value === undefined) return '';
    const s = String(value).replace(/\s+/g, ' ').trim();
    return s.length <= max ? s : `${s.slice(0, Math.max(1, max - 1))}…`;
}

/**
 * Render rows as an aligned text table. Columns that are empty in every row are dropped,
 * which keeps the output narrow without the caller having to pre-check.
 *
 * @param {{ key: string, label: string, align?: 'left' | 'right', max?: number }[]} columns
 * @param {Record<string, unknown>[]} rows
 * @param {{ indent?: string, keepEmpty?: boolean }} [opts]
 */
export function renderTable(columns, rows, opts = {}) {
    const indent = opts.indent ?? '';
    if (rows.length === 0) return `${indent}(none)`;
    const cells = rows.map((r) => columns.map((c) => clip(r[c.key], c.max ?? 80)));
    const used = columns
        .map((_, i) => i)
        .filter((i) => opts.keepEmpty || cells.some((row) => row[i] !== ''));
    const widths = used.map((i) => Math.max(columns[i].label.length, ...cells.map((row) => row[i].length)));
    /** @param {string[]} vals */
    const line = (vals) =>
        indent +
        used
            .map((i, j) => (columns[i].align === 'right' ? vals[i].padStart(widths[j]) : vals[i].padEnd(widths[j])))
            .join('  ')
            .trimEnd();
    return [line(columns.map((c) => c.label)), ...cells.map(line)].join('\n');
}

/**
 * Enforce an output budget in bytes (UTF-8). Cuts on a line boundary and says so.
 * @param {string} text
 * @param {number} maxBytes
 * @param {string} hint what the caller can do to get the rest
 */
export function applyBudget(text, maxBytes, hint) {
    if (Buffer.byteLength(text, 'utf8') <= maxBytes) return { text, truncated: false };
    const lines = text.split('\n');
    const kept = [];
    let size = 0;
    for (const l of lines) {
        const add = Buffer.byteLength(l, 'utf8') + 1;
        if (size + add > maxBytes - 200) break;
        kept.push(l);
        size += add;
    }
    const dropped = lines.length - kept.length;
    kept.push('', `[truncated: output budget ${Math.round(maxBytes / 1024)} KB reached, ${dropped} lines dropped. ${hint}]`);
    return { text: kept.join('\n'), truncated: true };
}

/**
 * Name matcher for `pattern` arguments. `*` and `%` match any run, `?` one character.
 * Without a wildcard the pattern is a case-insensitive "contains". `_` is literal, because
 * underscores are everywhere in these schemas and nobody means "any character" by them.
 * @param {string | undefined} pattern
 * @returns {(name: string) => boolean}
 */
export function nameMatcher(pattern) {
    if (!pattern || !pattern.trim()) return () => true;
    const p = pattern.trim();
    if (!/[*%?]/.test(p)) {
        const needle = p.toLowerCase();
        return (name) => name.toLowerCase().includes(needle);
    }
    const body = p
        .split('')
        .map((ch) => {
            if (ch === '*' || ch === '%') return '.*';
            if (ch === '?') return '.';
            return ch.replace(/[.+^${}()|[\]\\]/g, '\\$&');
        })
        .join('');
    const rx = new RegExp(`^${body}$`, 'i');
    return (name) => rx.test(name);
}

/**
 * Quote an identifier the way PostgreSQL would need it written.
 * @param {string} ident
 */
export function quoteIdent(ident) {
    return /^[a-z_][a-z0-9_$]*$/.test(ident) ? ident : `"${ident.replace(/"/g, '""')}"`;
}
