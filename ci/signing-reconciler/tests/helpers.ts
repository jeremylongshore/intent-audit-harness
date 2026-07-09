/**
 * helpers.ts — deterministic test doubles for the reconciler seams.
 *
 * These are INJECTED (never mocking a global): a scripted transport, and factory
 * builders for kernel-valid SkillVersion rows in each signing status. The
 * InMemoryOutbox from src/outbox.ts is reused directly (it is already a pure,
 * deterministic append-only impl).
 */

import type { RekorPushResult, RekorTransport, SkillVersion } from '../src/types.ts';

/**
 * A transport whose result is fully scripted per call. Records every version it
 * was asked to push so tests can assert it was (or was not) invoked, and that it
 * NEVER fakes delivery unless explicitly scripted to.
 */
export class ScriptedRekorTransport implements RekorTransport {
  readonly calls: SkillVersion[] = [];
  readonly #results: RekorPushResult[];
  #i = 0;

  constructor(results: readonly RekorPushResult[]) {
    this.#results = [...results];
  }

  push(version: SkillVersion): Promise<RekorPushResult> {
    this.calls.push(version);
    const result = this.#results[this.#i] ?? this.#results[this.#results.length - 1];
    this.#i += 1;
    if (result === undefined) {
      throw new Error('ScriptedRekorTransport: no scripted result for this call');
    }
    return Promise.resolve(result);
  }
}

/** A success result carrying a production Rekor index. */
export function delivered(logIndex: number): RekorPushResult {
  return { delivered: true, logIndex };
}

/** A failure result. */
export function undelivered(reason = 'rekor unreachable'): RekorPushResult {
  return { delivered: false, reason };
}

const HASH64 = 'a'.repeat(64);
const HASH64B = 'b'.repeat(64);
const HASH64C = 'c'.repeat(64);
const ROOT_ID = '0192cae6-000b-7000-8000-000000000000';

/**
 * Build a kernel-valid `pending_production` SkillVersion row. Overrides are merged
 * shallowly so a test can set retry_count / retry_after precisely.
 */
export function pendingRow(overrides: Partial<SkillVersion> = {}): SkillVersion {
  return {
    id: '0192cae6-000b-7000-8000-000000000011',
    skill_id: 'validate-skillmd',
    version_kind: 'edit',
    parent_version_id: ROOT_ID,
    content_hash: HASH64B,
    parent_content_hash: HASH64C,
    source_snapshot_hash: HASH64,
    refiner_strategy_id: 'naive-in-context@1',
    created_at: '2026-07-09T00:00:00Z',
    created_by: 'refiner-worker@intentsolutions.io',
    status: 'pending_production',
    signing_mode: 'sigstore_staging',
    retry_after: '2026-07-09T00:00:00Z',
    retry_count: 0,
    ...overrides,
  } as SkillVersion;
}

/** Build a kernel-valid `sigstore_staging` row (a row that never requested production). */
export function stagingRow(overrides: Partial<SkillVersion> = {}): SkillVersion {
  return {
    id: '0192cae6-000b-7000-8000-000000000010',
    skill_id: 'validate-skillmd',
    version_kind: 'edit',
    parent_version_id: ROOT_ID,
    content_hash: HASH64,
    parent_content_hash: HASH64C,
    source_snapshot_hash: HASH64,
    refiner_strategy_id: 'naive-in-context@1',
    created_at: '2026-07-09T00:00:00Z',
    created_by: 'refiner-worker@intentsolutions.io',
    status: 'sigstore_staging',
    signing_mode: 'sigstore_staging',
    ...overrides,
  } as SkillVersion;
}

/** Build a kernel-valid `active` + `rekor_production` row (already signed, terminal). */
export function activeRow(overrides: Partial<SkillVersion> = {}): SkillVersion {
  return {
    id: '0192cae6-000b-7000-8000-000000000012',
    skill_id: 'validate-skillmd',
    version_kind: 'edit',
    parent_version_id: ROOT_ID,
    content_hash: HASH64C,
    parent_content_hash: HASH64C,
    source_snapshot_hash: HASH64,
    refiner_strategy_id: 'naive-in-context@1',
    created_at: '2026-07-09T00:00:00Z',
    created_by: 'refiner-worker@intentsolutions.io',
    status: 'active',
    signing_mode: 'rekor_production',
    rekor_log_index: 1809941980,
    retry_count: 1,
    ...overrides,
  } as SkillVersion;
}
