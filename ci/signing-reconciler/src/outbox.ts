/**
 * outbox.ts — append-only signing OUTBOX implementations (AC-2).
 *
 * The OUTBOX is audit-harness's OWN append-only ledger of signing attempts,
 * DISTINCT from Rekor's transparency log. It exists so that — independent of
 * whether a Rekor push ever lands — there is a complete, ordered, tamper-evident-
 * by-construction (append-only) local record of every attempt the reconciler made.
 *
 * Two impls:
 *   - {@link InMemoryOutbox}   — deterministic, for tests + dry-run.
 *   - {@link JsonFileOutbox}   — the default runtime impl: newline-delimited JSON
 *                                (JSONL). Each `append` opens the file in APPEND
 *                                mode and writes exactly one line. It NEVER reads-
 *                                modifies-rewrites, so a crash mid-run can at worst
 *                                lose the in-flight line, never corrupt history.
 *
 * Neither impl exposes update or delete — the `SigningOutbox` interface has no
 * such method. Appends only. That is the AC-2 guarantee in code, not just prose.
 */

import { appendFile, readFile } from 'node:fs/promises';
import type { OutboxRecord, SigningOutbox } from './types.ts';

/**
 * In-memory append-only outbox. Backing array is private; `all()` returns a
 * defensive copy so callers cannot reach in and rewrite history.
 */
export class InMemoryOutbox implements SigningOutbox {
  readonly #records: OutboxRecord[] = [];

  append(record: OutboxRecord): Promise<void> {
    this.#records.push(record);
    return Promise.resolve();
  }

  all(): Promise<readonly OutboxRecord[]> {
    // Freeze a shallow copy — the OutboxRecord fields are readonly, and the copy
    // prevents a caller from push/splice-ing the internal array.
    return Promise.resolve([...this.#records]);
  }
}

/**
 * Default JSONL file outbox. Appends one JSON object per line. Reads parse every
 * non-blank line; a malformed line is FAIL-CLOSED (throws) rather than silently
 * skipped — a corrupt ledger must surface loudly, never be papered over.
 */
export class JsonFileOutbox implements SigningOutbox {
  readonly #path: string;

  constructor(path: string) {
    this.#path = path;
  }

  async append(record: OutboxRecord): Promise<void> {
    // One line, append mode. No read-modify-write; history is never rewritten.
    await appendFile(this.#path, `${JSON.stringify(record)}\n`, 'utf8');
  }

  async all(): Promise<readonly OutboxRecord[]> {
    let raw: string;
    try {
      raw = await readFile(this.#path, 'utf8');
    } catch (err: unknown) {
      // A not-yet-created ledger is an empty history, not an error.
      if (isEnoent(err)) return [];
      throw err;
    }
    const out: OutboxRecord[] = [];
    for (const [i, line] of raw.split('\n').entries()) {
      const trimmed = line.trim();
      if (trimmed === '') continue;
      try {
        out.push(JSON.parse(trimmed) as OutboxRecord);
      } catch (err: unknown) {
        throw new Error(
          `JsonFileOutbox: corrupt ledger line ${i + 1} in ${this.#path}: ${(err as Error).message}`,
        );
      }
    }
    return out;
  }
}

function isEnoent(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { code?: string }).code === 'ENOENT';
}
