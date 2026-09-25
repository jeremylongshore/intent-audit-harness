#!/usr/bin/env bash
# Contract suite for scripts/report-lineage.py.
#
# The fixtures model the J-Rig generic Run/Grade/report projection without
# opening SQLite or reaching the network. Every mutation is expected to become
# diagnosable ADVISORY by default and FAIL under --strict. Sampling indexes
# are unique within a cell; failed retries may leave gaps, and indexes may be
# reused by a different cell.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHECK="$ROOT/scripts/report-lineage.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0
FAIL=0

pass() { echo "  ok    $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL  $1" >&2; FAIL=$((FAIL + 1)); }

python3 - "$TMP" <<'PY'
import copy
import json
import math
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
selector = {
    "grader_id": "answer-checker",
    "grader_version": "1.0.0",
    "grader_snapshot_sha256": "sha256:" + "a" * 64,
}

def run(raw_id, status, task="task-a", config="config-a", sample=0, grade=None):
    return {
        "raw_run_id": raw_id,
        "task_id": task,
        "task_version": "1",
        "config_id": config,
        "config_version": "1",
        "model": "model-a",
        "sample_index": sample,
        "status": status,
        "grade": grade,
    }

def grade(verdict, score):
    return {**selector, "verdict": verdict, "score": score}

def wilson(successes, trials):
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    margin = z / denominator * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return {"lower": max(0, center - margin), "upper": min(1, center + margin), "confidence_level": 0.95}

def cell(runs):
    identity = runs[0]
    graded = [item["grade"] for item in runs if item["grade"] is not None]
    passes = sum(item["verdict"] == "pass" for item in graded)
    fails = sum(item["verdict"] == "fail" for item in graded)
    completed = sum(item["status"] == "completed" for item in runs)
    active = sum(item["status"] in {"pending", "running"} for item in runs)
    harness = sum(item["status"] in {"runner_error", "timed_out"} for item in runs)
    scores = [item["score"] for item in graded]
    rate = None if not graded else passes / len(graded)
    standard_error = None if rate is None else math.sqrt(rate * (1 - rate) / len(graded))
    mean = None if not scores else sum(scores) / len(scores)
    if len(scores) <= 1:
        score_se = None if not scores else 0
    else:
        variance = sum((score - mean) ** 2 for score in scores) / (len(scores) - 1)
        score_se = math.sqrt(variance / len(scores))
    return {
        "task_id": identity["task_id"], "task_version": identity["task_version"],
        "config_id": identity["config_id"], "config_version": identity["config_version"],
        "model": identity["model"],
        **selector,
        "attempted_runs": len(runs), "completed_runs": completed, "active_runs": active,
        "harness_failure_count": harness, "graded_runs": len(graded),
        "ungraded_completed_runs": completed - len(graded), "pass_count": passes, "fail_count": fails,
        "pass_rate": rate, "standard_error": standard_error,
        "confidence_interval_95": None if not graded else wilson(passes, len(graded)),
        "mean_score": mean, "score_standard_error": score_se,
    }

graded_pass = grade("pass", 1)
graded_fail = grade("fail", 0)
runs = [run("raw-0", "completed", sample=0, grade=graded_pass), run("raw-1", "completed", sample=1, grade=graded_fail), run("raw-2", "runner_error", sample=2)]
valid = {
    "schema": "j-rig/unified-report/v1", "generated_at": "2026-08-01T00:00:00.000Z", "grader": selector,
    "summary": {"cell_count": 1, "attempted_runs": 3, "completed_runs": 2, "active_runs": 0, "harness_failure_count": 1, "graded_runs": 2, "ungraded_completed_runs": 0, "pass_count": 1, "fail_count": 1},
    "cells": [cell(runs)], "runs": runs,
}
empty = {
    "schema": "j-rig/unified-report/v1", "generated_at": "2026-08-01T00:00:00.000Z", "grader": selector,
    "summary": {"cell_count": 0, "attempted_runs": 0, "completed_runs": 0, "active_runs": 0, "harness_failure_count": 0, "graded_runs": 0, "ungraded_completed_runs": 0, "pass_count": 0, "fail_count": 0},
    "cells": [], "runs": [],
}
ungraded_run = run("raw-ungraded", "completed", sample=0)
ungraded = {
    "schema": "j-rig/unified-report/v1", "generated_at": "2026-08-01T00:00:00.000Z", "grader": selector,
    "summary": {"cell_count": 1, "attempted_runs": 1, "completed_runs": 1, "active_runs": 0, "harness_failure_count": 0, "graded_runs": 0, "ungraded_completed_runs": 1, "pass_count": 0, "fail_count": 0},
    "cells": [cell([ungraded_run])], "runs": [ungraded_run],
}
retry_runs = [
    run("raw-retry-failed", "runner_error", sample=0),
    run("raw-retry-success", "completed", sample=2, grade=graded_pass),
]
retry_gap = {
    "schema": "j-rig/unified-report/v1", "generated_at": "2026-08-01T00:00:00.000Z", "grader": selector,
    "summary": {"cell_count": 1, "attempted_runs": 2, "completed_runs": 1, "active_runs": 0, "harness_failure_count": 1, "graded_runs": 1, "ungraded_completed_runs": 0, "pass_count": 1, "fail_count": 0},
    "cells": [cell(retry_runs)], "runs": retry_runs,
}
second_cell_runs = [run("raw-b0", "completed", task="task-b", config="config-b", sample=0, grade=graded_pass)]
multi_cell_runs = runs + second_cell_runs
multi_cell = {
    "schema": "j-rig/unified-report/v1", "generated_at": "2026-08-01T00:00:00.000Z", "grader": selector,
    "summary": {"cell_count": 2, "attempted_runs": 4, "completed_runs": 3, "active_runs": 0, "harness_failure_count": 1, "graded_runs": 3, "ungraded_completed_runs": 0, "pass_count": 2, "fail_count": 1},
    "cells": [cell(runs), cell(second_cell_runs)], "runs": multi_cell_runs,
}
suite = {
    "schema": "j-rig/suite-report/v1", "suite_id": "demo-suite", "suite_version": "1", "manifest_path": "suite.yaml",
    "generated_at": "2026-08-01T00:00:00.000Z", "raw_run_ids": [item["raw_run_id"] for item in runs], "report": valid,
}
source = {
    "schema": "j-rig/eval-suite/v1", "suite_id": "demo-suite", "suite_version": "1", "manifest_path": "suite.yaml",
    "jobs": [
        {**{key: item[key] for key in ("raw_run_id", "task_id", "task_version", "config_id", "config_version", "model")}, "status": item["status"], "grade": item["grade"]}
        for item in runs
    ],
    "report": {"raw_run_count": 3},
}

def write(name, value):
    (out / name).write_text(json.dumps(value, indent=2) if value != "MALFORMED" else "{\n", encoding="utf-8")

write("unified-valid.json", valid)
write("unified-empty.json", empty)
write("unified-ungraded.json", ungraded)
write("suite-valid.json", suite)
write("audit-valid.json", source)

duplicate = copy.deepcopy(valid)
duplicate["runs"][1]["raw_run_id"] = "raw-0"
write("duplicate.json", duplicate)

summary_drift = copy.deepcopy(valid)
summary_drift["summary"]["completed_runs"] = 1
write("summary-drift.json", summary_drift)

cell_drift = copy.deepcopy(valid)
cell_drift["cells"][0]["pass_count"] = 0
write("cell-drift.json", cell_drift)

grader_drift = copy.deepcopy(valid)
grader_drift["runs"][0]["grade"]["grader_snapshot_sha256"] = "sha256:" + "b" * 64
write("grader-drift.json", grader_drift)

status_drift = copy.deepcopy(valid)
status_drift["runs"][0]["status"] = "runner_error"
write("status-drift.json", status_drift)

source_drift = copy.deepcopy(source)
source_drift["jobs"][2]["raw_run_id"] = "raw-missing"
write("audit-drift.json", source_drift)

source_unsealed = copy.deepcopy(source)
source_unsealed["jobs"][2]["status"] = "failed"
write("audit-unsealed.json", source_unsealed)

sample_duplicate = copy.deepcopy(valid)
sample_duplicate["runs"][1]["sample_index"] = 0
write("sample-duplicate.json", sample_duplicate)

sample_malformed = copy.deepcopy(valid)
sample_malformed["runs"][0]["sample_index"] = -1
write("sample-malformed.json", sample_malformed)

write("retry-gap.json", retry_gap)
write("multi-cell.json", multi_cell)
write("malformed.json", "MALFORMED")
PY

assert_result() {
  local desc="$1" report="$2" expected_rc="$3" expected_result="$4" audit="${5:-}" strict="${6:-0}"
  local output="$TMP/output.json" rc actual
  local -a args=(python3 "$CHECK" --report "$report" --json)
  [[ -n "$audit" ]] && args+=(--audit-manifest "$audit")
  [[ "$strict" == "1" ]] && args+=(--strict)
  "${args[@]}" >"$output" 2>&1
  rc=$?
  actual="$(python3 - "$output" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["result"])
PY
  )"
  if [[ "$rc" == "$expected_rc" && "$actual" == "$expected_result" ]]; then
    pass "$desc -> $actual (exit $rc)"
  else
    fail "$desc -> got $actual (exit $rc), wanted $expected_result (exit $expected_rc)"
    sed -n '1,12p' "$output" >&2
  fi
}

echo "report-lineage contract tests"
echo "─────────────────────────────"
assert_result "valid unified report" "$TMP/unified-valid.json" 0 PASS
assert_result "valid empty report is explicit no-data" "$TMP/unified-empty.json" 0 PASS
assert_result "ungraded completed Run remains valid" "$TMP/unified-ungraded.json" 0 PASS
assert_result "failed retry gaps remain valid" "$TMP/retry-gap.json" 0 PASS
assert_result "sample indexes may repeat across distinct cells" "$TMP/multi-cell.json" 0 PASS
assert_result "duplicate Raw Run id is advisory" "$TMP/duplicate.json" 0 ADVISORY
assert_result "duplicate sample index is advisory" "$TMP/sample-duplicate.json" 0 ADVISORY
assert_result "malformed sample index is advisory" "$TMP/sample-malformed.json" 0 ADVISORY
assert_result "summary arithmetic drift is advisory" "$TMP/summary-drift.json" 0 ADVISORY
assert_result "cell arithmetic drift is advisory" "$TMP/cell-drift.json" 0 ADVISORY
assert_result "Grader snapshot mismatch is advisory" "$TMP/grader-drift.json" 0 ADVISORY
assert_result "Run/Grade status mismatch is advisory" "$TMP/status-drift.json" 0 ADVISORY
assert_result "strict mode gates summary drift" "$TMP/summary-drift.json" 1 FAIL "" 1
assert_result "strict mode gates duplicate sample index" "$TMP/sample-duplicate.json" 1 FAIL "" 1
assert_result "malformed report withholds clean claim" "$TMP/malformed.json" 0 ADVISORY
assert_result "missing report withholds clean claim" "$TMP/does-not-exist.json" 0 ADVISORY
assert_result "valid suite report matches audit source" "$TMP/suite-valid.json" 0 PASS "$TMP/audit-valid.json"
assert_result "suite report requires audit source" "$TMP/suite-valid.json" 0 ADVISORY
assert_result "suite/source Raw Run mismatch is advisory" "$TMP/suite-valid.json" 0 ADVISORY "$TMP/audit-drift.json"
assert_result "unsealed source status is advisory" "$TMP/suite-valid.json" 0 ADVISORY "$TMP/audit-unsealed.json"
assert_result "strict mode gates source mismatch" "$TMP/suite-valid.json" 1 FAIL "$TMP/audit-drift.json" 1

valid_diagnostic="$TMP/valid-diagnostic.json"
if python3 "$CHECK" --report "$TMP/unified-valid.json" --json >"$valid_diagnostic" \
  && python3 - "$valid_diagnostic" <<'PY'
import json, sys
row = json.load(open(sys.argv[1], encoding="utf-8"))
assert row["gate_id"] == "audit-harness:ci:report-lineage"
metadata = row["metadata"]
assert metadata["selected_grader"] == {
    "grader_id": "answer-checker",
    "grader_version": "1.0.0",
    "grader_snapshot_sha256": "sha256:" + "a" * 64,
}
assert metadata["run_counts"] == {
    "cell_count": 1,
    "attempted_runs": 3,
    "completed_runs": 2,
    "active_runs": 0,
    "harness_failure_count": 1,
    "graded_runs": 2,
    "ungraded_completed_runs": 0,
    "pass_count": 1,
    "fail_count": 1,
}
assert metadata["sample_balance"]["duplicate_sample_index_count"] == 0
PY
then pass "clean row carries canonical gate identity, Grader, Run counts, and sample metadata"
else fail "clean row omitted promotion binding metadata"; fi

sample_diagnostic="$TMP/sample-diagnostic.json"
if python3 "$CHECK" --report "$TMP/sample-duplicate.json" --json >"$sample_diagnostic" \
  && python3 - "$sample_diagnostic" <<'PY'
import json, sys
row = json.load(open(sys.argv[1], encoding="utf-8"))
assert row["metadata"]["sample_balance"]["duplicate_sample_index_count"] == 1
assert any("duplicate sample_index 0" in error for error in row["metadata"]["errors"])
PY
then pass "sample-balance finding carries deterministic diagnostics"
else fail "sample-balance finding did not carry deterministic diagnostics"; fi

dispatcher_output="$TMP/dispatcher.json"
if node "$ROOT/bin/audit-harness.js" report-lineage --report "$TMP/unified-empty.json" --json >"$dispatcher_output" 2>&1 \
  && python3 - "$dispatcher_output" <<'PY'
import json, sys
assert json.load(open(sys.argv[1], encoding="utf-8"))["result"] == "PASS"
PY
then pass "Node dispatcher exposes report-lineage"
else fail "Node dispatcher did not expose report-lineage"; fi

statement_output="$TMP/statement.json"
if node "$ROOT/bin/audit-harness.js" report-lineage --report "$TMP/unified-empty.json" --json \
  | bash "$ROOT/scripts/emit-evidence.sh" >"$statement_output" \
  && python3 - "$statement_output" <<'PY'
import json, sys
statement = json.load(open(sys.argv[1], encoding="utf-8"))
assert statement["predicateType"].endswith("/gate-result/v1")
assert statement["predicate"]["gate_id"] == "audit-harness:ci:report-lineage"
PY
then pass "report-lineage JSON pipes through emit-evidence"
else fail "report-lineage JSON did not emit a valid gate-result Statement"; fi

echo "─────────────────────────────"
echo "report-lineage results: PASS=${PASS}  FAIL=${FAIL}"
[[ "$FAIL" -eq 0 ]] || exit 1
