#!/usr/bin/env python3
"""
audit-harness conform — read-only deterministic conformance gate-runner.

For every conformance-dimension gate in a repo's audit-profile/v1, conform locates
the relevant artifact(s) and validates them against a CONTENT-ADDRESSED schema
BUNDLED in this harness version (never live-fetched). Each artifact yields one
`gate-result/v1` Evidence Bundle row (the predicate body in
schemas/.../gate-result.schema.json / @intentsolutions/core), emitted as a JSON
array on stdout. NEVER writes to the repo.

Design rules (PP-PLAN-040 Phase 2):
  - Deterministic + pure-local. Same commit + same harness version => identical
    verdict. The bundled JSON-Schema is validated by an EMBEDDED subset validator
    (not ajv) precisely BECAUSE ajv's availability/version varies per box and would
    make signed evidence non-reproducible. The embedded validator is complete for
    the closed bundled schemas (which use only the keyword subset it supports).
  - Genuinely-external formats shell out: OpenAPI -> spectral, Action YAML ->
    yamllint. Missing tool => INDETERMINATE (advisory), never a false FAIL.
  - Advisory-first. A conformance violation on an `enforcement: advisory` gate is
    ADVISORY (severity error), exit 0 — the finding is logged, the build is not
    reddened. Only an engineer-promoted `enforcement: blocking` gate (or --strict)
    turns a violation into FAIL (exit 1).
  - conform records the bundled schema's sha256 in the gate-result `policy_hash`,
    so a row re-verifies against the exact schema version that produced it.
  - Stdlib only (PyYAML used for frontmatter when present; absent => indeterminate
    rather than a guessed verdict). No network. No filesystem mutation.

Tiers (--tier, default `floor`):
  floor        the harness's own conform/v1 structural floor (name + description
               for SKILL.md). Unchanged default, so existing consumers see the
               same verdicts.
  marketplace  Published authoring/v1 contracts for skills, agents, plugins,
               catalogs, MCP entries and hook handlers. MCP/hook envelopes are
               projected without inventing defaults, binding original bytes.
               Schemas are vendored unmodified and hash-pinned. Unsupported
               inputs or a pin mismatch yield indeterminate ADVISORY.


Usage:
  python3 scripts/conform.py [REPO_PATH] [--json] [--strict] [--tier floor|marketplace] [--profile PATH|-]
  AUDIT_HARNESS_DISABLE=1 python3 scripts/conform.py   # kill-switch (no-op, exit 0)
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import classify as C  # noqa: E402  (sibling module; reused for the single-source profile)
from authoring_discovery import embedded_artifacts  # noqa: E402
from authoring_inputs import (  # noqa: E402
    InvalidArtifact, UnmeasuredReference, read_frontmatter_snapshot, read_frontmatter_document,
    read_json_snapshot, reference_path,
)
from authoring_projection import ProjectionError, component_parts, project_hooks, project_mcp  # noqa: E402
from shared_authoring import agent_findings, combined_policy_hash, load_agent_checker  # noqa: E402

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - exercised only on boxes without PyYAML
    yaml = None

SCHEMA_DIR = os.path.join(HERE, "..", "schemas", "conform", "v1")
KERNEL_DIR = os.path.join(HERE, "..", "schemas", "conform", "kernel", "intent-eval-core-0.11.0")
TIERS = ("floor", "marketplace")
EMPTY_SHA = "sha256:" + hashlib.sha256(b"").hexdigest()

# kind -> bundled schema filename (content-addressed in this harness version)
BUNDLED = {
    "skillmd": "skillmd-frontmatter.schema.json",
    "agent": "agent-frontmatter.schema.json",
    "mcp": "mcp-config.schema.json",
    "plugin": "plugin-manifest.schema.json",
}
FRONTMATTER_KINDS = {"skillmd", "agent"}      # YAML frontmatter in a .md file
JSON_KINDS = {"mcp", "plugin", "marketplace", "hook"}  # whole-file JSON
SHELLOUT = {                                   # genuinely-external linters
    "openapi": "spectral",
    "action": "yamllint",
}


# --------------------------------------------------------------------------- #
# Embedded JSON-Schema subset validator (complete for the closed bundled schemas)
# --------------------------------------------------------------------------- #
def _type_ok(value, t):
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "null":
        return value is None
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    return True


def _resolve_ref(ref, ctx):
    """Resolve a $ref against ctx = {"root": doc, "registry": {$id: doc}}.

    Supports what the vendored kernel composition uses: absolute $id URIs,
    same-document fragments, and RFC 6901 JSON pointers. Returns (schema, new_ctx)
    or (None, None) when the target is not registered locally — the harness never
    fetches a schema over the network."""
    uri, _, frag = ref.partition("#")
    if uri:
        doc = ctx["registry"].get(uri)
        if doc is None:
            return None, None
    else:
        doc = ctx["root"]
    node = doc
    if frag:
        for tok in frag.lstrip("/").split("/"):
            tok = tok.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and tok in node:
                node = node[tok]
            else:
                return None, None
    return node, {"root": doc, "registry": ctx["registry"]}


def kernel_schema_admission(schema, registry):
    """Refuse unsupported reachable kernel assertions rather than silently ignore them."""
    supported = {
        "$schema", "$id", "$ref", "$defs", "$comment", "title", "description",
        "default", "examples", "type", "enum", "const", "minLength", "maxLength",
        "pattern", "format", "minimum", "minItems", "maxItems", "items", "required",
        "properties", "additionalProperties", "allOf", "anyOf", "oneOf", "not",
        # Published kyh9 annotation explicitly belongs to generated Zod, not JSON Schema.
        "x-mutually-exclusive-fields",
    }
    active, checked = set(), set()

    def visit(node, ctx):
        if not isinstance(node, dict):
            return "unsupported non-object kernel schema"
        identity = (id(node), id(ctx["root"]))
        if identity in active:
            return "recursive kernel schema is unsupported"
        if identity in checked:
            return None
        unknown = sorted(set(node) - supported)
        if unknown:
            return "unsupported kernel schema keyword: " + ", ".join(unknown)
        if "format" in node and node["format"] not in ("uri", "url"):
            return "unsupported kernel schema format: " + str(node["format"])
        active.add(identity)
        children = [(child, ctx) for child in node.get("properties", {}).values()]
        for keyword in ("items", "not"):
            if keyword in node:
                children.append((node[keyword], ctx))
        if isinstance(node.get("additionalProperties"), dict):
            children.append((node["additionalProperties"], ctx))
        for keyword in ("allOf", "anyOf", "oneOf"):
            children.extend((child, ctx) for child in node.get(keyword, []))
        if "$ref" in node:
            target, target_ctx = _resolve_ref(node["$ref"], ctx)
            if target is None:
                return "unresolvable kernel schema reference: " + node["$ref"]
            children.append((target, target_ctx))
        for child, child_ctx in children:
            reason = visit(child, child_ctx)
            if reason:
                return reason
        active.remove(identity)
        checked.add(identity)
        return None

    return visit(schema, {"root": schema, "registry": registry})


def validate_instance(inst, schema, path="$", _ctx=None):
    """Return a list of human-readable violation strings ([] == valid)."""
    errs = []
    if not isinstance(schema, dict):
        return errs
    ctx = _ctx if _ctx is not None else {"root": schema, "registry": {}}

    def sub(i, sch, p, c=None):
        return validate_instance(i, sch, p, c if c is not None else ctx)

    if "$ref" in schema:
        target, rctx = _resolve_ref(schema["$ref"], ctx)
        if target is None:
            errs.append(f"{path}: unresolvable $ref {schema['$ref']!r} (not bundled)")
        else:
            errs += sub(inst, target, path, rctx)

    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(inst, x) for x in types):
            errs.append(f"{path}: expected type {t}, got {type(inst).__name__}")
            return errs  # downstream keyword checks are meaningless on a type mismatch

    if "enum" in schema and inst not in schema["enum"]:
        errs.append(f"{path}: {inst!r} not in enum {schema['enum']}")
    if "const" in schema and inst != schema["const"]:
        errs.append(f"{path}: {inst!r} != const {schema['const']!r}")

    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            errs.append(f"{path}: below minimum {schema['minimum']}")

    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            errs.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            errs.append(f"{path}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], inst) is None:
            errs.append(f"{path}: does not match pattern {schema['pattern']!r}")
        if schema.get("format") in ("uri", "url") and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", inst):
            errs.append(f"{path}: not a {schema['format']}")

    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            errs.append(f"{path}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(inst) > schema["maxItems"]:
            errs.append(f"{path}: more than maxItems {schema['maxItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, el in enumerate(inst):
                errs += sub(el, item_schema, f"{path}[{i}]")

    if isinstance(inst, dict):
        for req in schema.get("required", []):
            if req not in inst:
                errs.append(f"{path}: missing required property '{req}'")
        props = schema.get("properties", {})
        for k, sch_k in props.items():
            if k in inst:
                errs += sub(inst[k], sch_k, f"{path}.{k}")
        ap = schema.get("additionalProperties", True)
        if ap is False:
            for k in inst:
                if k not in props:
                    errs.append(f"{path}: additional property '{k}' not allowed")
        elif isinstance(ap, dict):
            for k, v in inst.items():
                if k not in props:
                    errs += sub(v, ap, f"{path}.{k}")

    for s_all in schema.get("allOf", []):
        errs += sub(inst, s_all, path)
    if "anyOf" in schema:
        if not any(not sub(inst, s_any, path) for s_any in schema["anyOf"]):
            errs.append(f"{path}: matches none of anyOf")
    if "not" in schema and not sub(inst, schema["not"], path):
        shown = json.dumps(schema["not"], sort_keys=True)
        if len(shown) > 160:
            shown = shown[:157] + "..."
        errs.append(f"{path}: must NOT match {shown}")
    if "oneOf" in schema:
        matches = sum(1 for s_one in schema["oneOf"] if not sub(inst, s_one, path))
        if matches != 1:
            errs.append(f"{path}: matched {matches} of oneOf branches (need exactly 1)")
    return errs


# --------------------------------------------------------------------------- #
# Artifact location + parsing
# --------------------------------------------------------------------------- #
SKIP_DIRS = ("node_modules", ".git", ".venv", "dist", "build",
             "fixtures", "tests", "test", "__tests__", "examples")


def find_files(repo, name, max_depth=3):
    repo = os.path.abspath(repo)
    out = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        depth = root[len(repo):].count(os.sep)
        if depth > max_depth:
            dirs[:] = []
            continue
        if name in files:
            out.append(os.path.join(root, name))
    return sorted(out)


def locate(kind, repo):
    """Return the list of artifact file paths for a conformance kind."""
    repo = os.path.abspath(repo)

    def first_existing(*rels):
        return [os.path.join(repo, r) for r in rels if os.path.isfile(os.path.join(repo, r))]

    if kind == "skillmd":
        return find_files(repo, "SKILL.md")
    if kind == "agent":
        out = []
        for d in (os.path.join(repo, "agents"), os.path.join(repo, ".claude", "agents")):
            if os.path.isdir(d):
                out += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".md")]
        return out
    if kind == "mcp":
        out = first_existing(".mcp.json")
        for sub in C.list_pkg_subdirs(repo):
            p = os.path.join(sub, ".mcp.json")
            if os.path.isfile(p):
                out.append(p)
        return out
    if kind == "plugin":
        return first_existing(".claude-plugin/plugin.json", "plugin.json")
    if kind == "marketplace":
        return first_existing(".claude-plugin/marketplace.json", "marketplace.json")
    if kind == "hook":
        out = first_existing("hooks/hooks.json")
        hd = os.path.join(repo, ".claude", "hooks")
        if os.path.isdir(hd):
            out += [os.path.join(hd, f) for f in sorted(os.listdir(hd)) if f.endswith(".json")]
        return out
    if kind == "openapi":
        return first_existing("openapi.yaml", "openapi.yml", "openapi.json",
                              "swagger.yaml", "swagger.json")
    if kind == "action":
        return first_existing("action.yml", "action.yaml")
    return []


def parse_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        return None, f"json-parse-error: {e}"
    except Exception as e:
        return None, f"read-error: {e}"


def extract_frontmatter(path):
    """Return (dict, None) or (None, reason). Requires PyYAML for a reliable verdict."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        return None, f"read-error: {e}"
    if not text.lstrip().startswith("---"):
        return None, "no-frontmatter-block"
    m = re.match(r"^﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(\r?\n|$)", text, re.DOTALL)
    if not m:
        return None, "unterminated-frontmatter-block"
    block = m.group(1)
    if yaml is None:
        return None, "pyyaml-unavailable"  # honest indeterminate, not a guessed parse
    try:
        data = yaml.safe_load(block)
    except Exception as e:
        return None, f"yaml-parse-error: {e}"
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, "frontmatter-not-a-mapping"
    return data, None


# --------------------------------------------------------------------------- #
# gate-result/v1 row construction
# --------------------------------------------------------------------------- #
def sha256_path(path):
    try:
        return C.sha256_file(path)
    except Exception:
        return EMPTY_SHA


def sha256_str(s):
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def make_row(gate_id, result, *, policy_hash, input_hash, commit_sha, runner,
             metadata=None, failure_mode=None, advisory_severity=None):
    row = {
        "gate_id": gate_id,
        "result": result,
        "policy_hash": policy_hash,
        "input_hash": input_hash,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runner": runner,
        "commit_sha": commit_sha,
    }
    if metadata:
        row["metadata"] = metadata
    if failure_mode is not None:
        row["failure_mode"] = failure_mode
    if advisory_severity is not None:
        row["advisory_severity"] = advisory_severity
    return row


def verdict_for(errs, parse_err, enforcement, strict):
    """Map (violations, parse error, enforcement) -> (result, failure_mode, severity)."""
    violated = bool(errs) or parse_err is not None
    if not violated:
        return "PASS", None, None
    blocking = strict or enforcement == "blocking"
    if blocking:
        fm = "conform:parse-error" if parse_err is not None else "conform:schema-violation"
        return "FAIL", fm, None
    return "ADVISORY", None, "error"


# --------------------------------------------------------------------------- #
def compute_profile(repo, registry_path, profile_arg, embedded_authoring=False):
    if profile_arg == "-":
        return json.load(sys.stdin)
    if profile_arg:
        with open(profile_arg, "r", encoding="utf-8") as f:
            return json.load(f)
    out = subprocess.run(
        [sys.executable, os.path.join(HERE, "classify.py"), repo, "--registry", registry_path]
        + (["--embedded-authoring"] if embedded_authoring else []),
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.stderr.write(out.stderr)
        raise SystemExit(2)
    return json.loads(out.stdout)


def kind_of(gate_id):
    """audit-harness:local:conform-skillmd -> 'skillmd'."""
    seg = gate_id.rsplit(":", 1)[-1]
    return seg[len("conform-"):] if seg.startswith("conform-") else seg


def run_shellout(kind, gate, files, commit_sha, runner, repo, strict):
    tool = SHELLOUT[kind]
    rows = []
    enforcement = gate.get("enforcement", "advisory")
    if shutil.which(tool) is None:
        rows.append(make_row(
            gate["gate_id"], "ADVISORY",
            policy_hash=sha256_str(f"{tool}:default"),
            input_hash=sha256_path(files[0]) if files else EMPTY_SHA,
            commit_sha=commit_sha, runner=runner, advisory_severity="warn",
            metadata={"kind": kind, "validator": tool, "indeterminate": True,
                      "reason": f"{tool} not on PATH — conformance unmeasured"},
        ))
        return rows
    for art in files:
        cmd = [tool, "lint", art] if tool == "spectral" else [tool, art]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            errs = [] if proc.returncode == 0 else [(proc.stdout or proc.stderr).strip()[:2000]]
            parse_err = None
        except Exception as e:
            errs, parse_err = [], None
            rows.append(make_row(
                gate["gate_id"], "ADVISORY",
                policy_hash=sha256_str(f"{tool}:default"), input_hash=sha256_path(art),
                commit_sha=commit_sha, runner=runner, advisory_severity="warn",
                metadata={"kind": kind, "validator": tool, "indeterminate": True,
                          "artifact_path": os.path.relpath(art, repo), "reason": str(e)},
            ))
            continue
        result, fm, sev = verdict_for(errs, parse_err, enforcement, strict)
        rows.append(make_row(
            gate["gate_id"], result,
            policy_hash=sha256_str(f"{tool}:default"), input_hash=sha256_path(art),
            commit_sha=commit_sha, runner=runner, failure_mode=fm, advisory_severity=sev,
            metadata={"kind": kind, "validator": tool,
                      "artifact_path": os.path.relpath(art, repo),
                      "errors": errs[:20]},
        ))
    return rows


def load_kernel(kind, kernel_dir=None):
    """Load the pinned kernel schema for `kind`.

    Returns (schema, registry, policy_hash, kernel_label, None) on success or
    (None, None, None, None, reason) when the pin cannot be honoured. Every
    vendored file must match its sha256 in pin.json; the policy_hash is the
    sha256 of pin.json itself, which commits to every file hash."""
    kdir = kernel_dir or KERNEL_DIR
    pin_path = os.path.join(kdir, "pin.json")
    pin = C.read_json(pin_path)
    if not isinstance(pin, dict):
        return None, None, None, None, "kernel pin.json missing or unreadable"
    entry = pin.get("entries", {}).get(kind)
    if not entry:
        return None, None, None, None, f"pinned kernel has no entry for kind '{kind}'"
    registry = {}
    for rel, want in sorted(pin.get("files", {}).items()):
        fpath = os.path.join(kdir, rel)
        if not os.path.isfile(fpath):
            return None, None, None, None, f"kernel file missing: {rel}"
        got = C.sha256_file(fpath)
        if got != want:
            return None, None, None, None, f"kernel file hash mismatch: {rel} ({got} != pinned {want})"
        doc = C.read_json(fpath)
        if isinstance(doc, dict) and doc.get("$id"):
            registry[doc["$id"]] = doc
    if entry not in pin.get("files", {}):
        return None, None, None, None, f"kernel entry {entry} is not pinned"
    schema = C.read_json(os.path.join(kdir, entry))
    reason = kernel_schema_admission(schema, registry)
    if reason:
        return None, None, None, None, reason
    label = f"{pin.get('package', '?')}@{pin.get('version', '?')}"
    return schema, registry, C.sha256_file(pin_path), label, None


def projected_targets(kind, repo, relative, mode, bindings):
    """Return located entries and retain every consumed artifact digest."""
    snapshots = {}

    def read(path, frontmatter=False):
        if path in snapshots:
            return snapshots[path]
        try:
            data, digest = (read_frontmatter_snapshot(repo, path) if frontmatter
                            else read_json_snapshot(repo, path))
        except (InvalidArtifact, UnmeasuredReference) as exc:
            if exc.input_hash:
                bindings[path] = exc.input_hash
            raise
        bindings[path] = digest
        snapshots[path] = data
        return data

    def project(data, *, bare=False, base=None):
        if kind == "mcp":
            return project_mcp(data, bare=bare, base=base)
        return project_hooks(data, bare=bare, base=base)

    data = read(relative, mode == "frontmatter")
    if mode == "manifest":
        field = "mcpServers" if kind == "mcp" else "hooks"
        targets = []
        for pointer, value in component_parts(data, field):
            if isinstance(value, dict):
                targets += project(value, bare=True, base=pointer)
            else:
                parent = os.path.dirname(relative)
                if os.path.basename(parent) == ".claude-plugin":
                    parent = os.path.dirname(parent)
                path = os.path.join(parent, reference_path(value)).replace(os.sep, "/")
                referenced = read(path)
                bare = kind == "mcp" and isinstance(referenced, dict) and "mcpServers" not in referenced
                targets += [(path + "#" + target, entry) for target, entry in project(referenced, bare=bare)]
        return targets
    if mode in ("settings", "frontmatter") and isinstance(data, dict) and "hooks" not in data:
        return []
    bare = kind == "mcp" and isinstance(data, dict) and "mcpServers" not in data
    return project(data, bare=bare)


def binding_hash(bindings):
    if len(bindings) == 1:
        return next(iter(bindings.values()))
    return sha256_str(json.dumps({"format": "authoring-inputs/v1", "files": bindings}, sort_keys=True))


def run_projected(kind, gate, files, commit_sha, runner, repo, strict):
    """Measure per-entry v1 contracts while binding the original JSON artifact."""
    schema, registry, policy_hash, label, reason = load_kernel(kind)
    if schema is None:
        return [make_row(gate["gate_id"], "ADVISORY", policy_hash=EMPTY_SHA, input_hash=EMPTY_SHA,
                         commit_sha=commit_sha, runner=runner, advisory_severity="warn",
                         metadata={"kind": kind, "tier": "marketplace", "indeterminate": True, "reason": reason})]
    rows = []
    modes = dict(embedded_artifacts(repo, kind))
    for artifact in files:
        relative = os.path.relpath(artifact, repo)
        meta = {"kind": kind, "tier": "marketplace", "kernel": label,
                "schema_id": schema.get("$id", ""), "artifact_path": relative,
                "validator": "audit-harness-embedded-subset", "projection": "authoring-envelope/v1"}
        digest, errors, parse_error, bindings = EMPTY_SHA, [], None, {}
        try:
            targets = projected_targets(kind, repo, relative, modes.get(relative, "standalone"), bindings)
            digest = binding_hash(bindings)
            meta["input_bindings"] = bindings
            meta["target_pointers"] = [path for path, _ in targets]
            if not targets:
                rows.append(make_row(gate["gate_id"], "NOT_APPLICABLE", policy_hash=policy_hash,
                                     input_hash=digest, commit_sha=commit_sha, runner=runner,
                                     metadata={**meta, "reason": "no declared measurement targets"}))
                continue
            for path, entry in targets:
                errors += validate_instance(entry, schema, path=path,
                                            _ctx={"root": schema, "registry": registry})
        except UnmeasuredReference as exc:
            digest = binding_hash(bindings) if bindings else (exc.input_hash or digest)
            meta["input_bindings"] = bindings
            rows.append(make_row(gate["gate_id"], "ADVISORY", policy_hash=policy_hash,
                                 input_hash=digest, commit_sha=commit_sha, runner=runner, advisory_severity="warn",
                                 metadata={**meta, "indeterminate": True, "reason": str(exc)}))
            continue
        except InvalidArtifact as exc:
            digest = binding_hash(bindings) if bindings else (exc.input_hash or EMPTY_SHA)
            parse_error = str(exc)
        except ProjectionError as exc:
            errors = [str(exc)]
            digest = binding_hash(bindings) if bindings else EMPTY_SHA
        meta["input_bindings"] = bindings
        result, failure_mode, severity = verdict_for(errors, parse_error, gate.get("enforcement", "advisory"), strict)
        if parse_error or errors:
            meta["errors"] = [parse_error] if parse_error else errors[:20]
        rows.append(make_row(gate["gate_id"], result, policy_hash=policy_hash, input_hash=digest,
                             commit_sha=commit_sha, runner=runner, failure_mode=failure_mode,
                             advisory_severity=severity, metadata=meta))
    return rows


def run_bundled(kind, gate, files, commit_sha, runner, repo, strict, tier="floor", shared_validators=False):
    if tier == "marketplace" and kind in ("mcp", "hook"):
        return run_projected(kind, gate, files, commit_sha, runner, repo, strict)
    rows = []
    enforcement = gate.get("enforcement", "advisory")
    registry = {}
    tier_meta = {"tier": "floor"}
    if tier == "marketplace" and kind in ("skillmd", "marketplace", "agent", "plugin"):
        schema, registry, policy_hash, label, reason = load_kernel(kind)
        if schema is None:
            rows.append(make_row(
                gate["gate_id"], "ADVISORY",
                policy_hash=EMPTY_SHA, input_hash=EMPTY_SHA, commit_sha=commit_sha,
                runner=runner, advisory_severity="warn",
                metadata={"kind": kind, "tier": "marketplace", "indeterminate": True,
                          "reason": reason},
            ))
            return rows
        tier_meta = {"tier": "marketplace", "kernel": label}
    else:
        schema_path = os.path.join(SCHEMA_DIR, BUNDLED[kind])
        schema = C.read_json(schema_path)
        if schema is None:
            rows.append(make_row(
                gate["gate_id"], "ADVISORY",
                policy_hash=EMPTY_SHA, input_hash=EMPTY_SHA, commit_sha=commit_sha,
                runner=runner, advisory_severity="warn",
                metadata={"kind": kind, "indeterminate": True,
                          "reason": f"bundled schema missing at {BUNDLED[kind]}"},
            ))
            return rows
        policy_hash = C.sha256_file(schema_path)
    schema_id = schema.get("$id", "")
    shared_agent = shared_validators and kind == "agent"
    schema_policy = policy_hash
    checker, shared_policy, checker_reason = (load_agent_checker() if shared_agent else (None, EMPTY_SHA, None))
    if shared_agent:
        policy_hash = combined_policy_hash(schema_policy, shared_policy)
    for art in files:
        input_digest, body, input_reason = None, "", None
        if shared_agent:
            try:
                data, body, input_digest = read_frontmatter_document(repo, os.path.relpath(art, repo))
                parse_err = None
            except InvalidArtifact as exc:
                data, parse_err, input_digest = None, str(exc), exc.input_hash or EMPTY_SHA
            except UnmeasuredReference as exc:
                data, parse_err, input_reason = None, None, str(exc)
                input_digest = exc.input_hash or EMPTY_SHA
        elif kind in FRONTMATTER_KINDS:
            data, parse_err = extract_frontmatter(art)
        else:
            data, parse_err = parse_json_file(art)

        if parse_err == "pyyaml-unavailable":
            rows.append(make_row(
                gate["gate_id"], "ADVISORY",
                policy_hash=policy_hash, input_hash=sha256_path(art), commit_sha=commit_sha,
                runner=runner, advisory_severity="warn",
                metadata={"kind": kind, "validator": "audit-harness-embedded-subset",
                          "schema_id": schema_id, "indeterminate": True, **tier_meta,
                          "artifact_path": os.path.relpath(art, repo),
                          "reason": "PyYAML unavailable — frontmatter conformance unmeasured"},
            ))
            continue

        errs = (validate_instance(data, schema, _ctx={"root": schema, "registry": registry})
                if parse_err is None and input_reason is None else [])
        shared_errors, shared_warnings, shared_reason = [], [], checker_reason or input_reason
        if shared_agent and checker is not None and parse_err is None and input_reason is None:
            shared_errors, shared_warnings, shared_reason = agent_findings(checker, data, body)
        result, fm, sev = verdict_for(errs + shared_errors, parse_err, enforcement, strict)
        if result == "FAIL" and shared_errors and not errs and parse_err is None:
            fm = "conform:shared-validator-violation"
        if result == "PASS" and (shared_warnings or shared_reason):
            result, sev = "ADVISORY", "warn"
        meta = {"kind": kind, "validator": "audit-harness-embedded-subset",
                "schema_id": schema_id, "artifact_path": os.path.relpath(art, repo),
                **tier_meta}
        if parse_err is not None:
            meta["errors"] = [parse_err]
        elif errs:
            meta["errors"] = errs[:20]
        if shared_agent:
            meta["schema_policy_hash"] = schema_policy
            meta["shared_validator"] = {
                "name": "agent-body-tools", "policy_hash": shared_policy, "static_only": True,
                "errors": shared_errors[:20], "warnings": shared_warnings[:20],
                "interpretation": "Lexical policy findings, not observed tool calls or runtime denials; "
                                  "omitted and empty tool lists share legacy findings, and inheritance is not modeled.",
            }
            if shared_reason:
                meta.update(indeterminate=True, reason=shared_reason)
        rows.append(make_row(
            gate["gate_id"], result, policy_hash=policy_hash,
            input_hash=input_digest if input_digest is not None else sha256_path(art),
            commit_sha=commit_sha, runner=runner, failure_mode=fm, advisory_severity=sev,
            metadata=meta,
        ))
    return rows


def main():
    ap = argparse.ArgumentParser(description="Read-only conformance gate-runner -> gate-result/v1 rows")
    ap.add_argument("repo", nargs="?", default=".", help="Repo path (default: cwd)")
    ap.add_argument("--json", action="store_true", help="Emit JSON (default; flag is for CLI symmetry)")
    ap.add_argument("--strict", action="store_true",
                    help="Treat every conformance violation as FAIL (exit 1), ignoring advisory default")
    ap.add_argument("--tier", choices=TIERS, default="floor",
                    help="Schema tier: 'floor' (default, harness conform/v1 floor) or 'marketplace' "
                         "(skills, agents, plugins, catalogs, MCP and hooks against pinned authoring/v1 contracts)")
    ap.add_argument("--registry", default=C.DEFAULT_REGISTRY, help="Path to the dimension-to-gate registry")
    ap.add_argument("--shared-validators", action="store_true",
                    help="Opt into pinned marketplace static checks (currently agent body/tool-list consistency)")
    ap.add_argument("--profile", default=None,
                    help="Use a pinned audit-profile/v1 (PATH or '-' for stdin) instead of classifying")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    registry_path = os.path.abspath(args.registry)
    runner = f"audit-harness@{C.harness_version()}"

    override_path = os.path.join(repo, ".audit-harness.yml")
    override = C.parse_override(override_path) if os.path.isfile(override_path) else {"disable": False}
    if override.get("disable") or os.environ.get("AUDIT_HARNESS_DISABLE") == "1":
        sys.stderr.write("audit-harness: KILL-SWITCH active — conform skipped (no rows emitted)\n")
        print("[]")
        sys.exit(0)

    profile = compute_profile(repo, registry_path, args.profile, embedded_authoring=args.tier == "marketplace")
    commit_sha = profile.get("subject", {}).get("commit_sha") or C.git_short_sha(repo)

    conf_gates = [g for g in profile.get("gates", [])
                  if g.get("dimension") == "conformance" and g.get("enforcement") != "disabled"]

    rows = []
    for gate in conf_gates:
        kind = kind_of(gate["gate_id"])
        files = locate(kind, repo)
        if args.tier == "marketplace" and kind in ("mcp", "hook"):
            files = sorted(set(files) | {os.path.join(repo, path) for path, _ in embedded_artifacts(repo, kind)})
        if not files:
            rows.append(make_row(
                gate["gate_id"], "NOT_APPLICABLE",
                policy_hash=EMPTY_SHA, input_hash=EMPTY_SHA, commit_sha=commit_sha,
                runner=runner, metadata={"kind": kind, "reason": "no matching artifact found in repo"},
            ))
            continue
        if kind in BUNDLED or (args.tier == "marketplace" and kind in ("marketplace", "hook")):
            rows += run_bundled(kind, gate, files, commit_sha, runner, repo, args.strict, args.tier,
                                shared_validators=args.shared_validators)
        elif kind in SHELLOUT:
            rows += run_shellout(kind, gate, files, commit_sha, runner, repo, args.strict)
        else:
            rows.append(make_row(
                gate["gate_id"], "ADVISORY",
                policy_hash=EMPTY_SHA, input_hash=sha256_path(files[0]), commit_sha=commit_sha,
                runner=runner, advisory_severity="warn",
                metadata={"kind": kind, "indeterminate": True,
                          "reason": f"no bundled conform schema for kind '{kind}' in this harness version"},
            ))

    print(json.dumps(rows, indent=2))

    n_fail = sum(1 for r in rows if r["result"] == "FAIL")
    n_adv = sum(1 for r in rows if r["result"] == "ADVISORY")
    n_pass = sum(1 for r in rows if r["result"] == "PASS")
    sys.stderr.write(f"audit-harness conform: {n_pass} PASS, {n_adv} ADVISORY, {n_fail} FAIL "
                     f"across {len(rows)} row(s)\n")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
