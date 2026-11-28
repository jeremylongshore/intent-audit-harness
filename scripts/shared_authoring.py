"""Load a pinned, marketplace-authored static checker from verified bytes.

Hashes identify the selected implementation; they are not an independent trust
root. Repository/release integrity and ordinary protected-file policy still apply.
"""

import hashlib
import re
from pathlib import Path

from authoring_inputs import (
    InvalidArtifact, UnmeasuredReference, read_bytes_snapshot, read_json_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
PIN = "schemas/conform/shared-validators/agent-body-tools.json"
MODULE = "scripts/agent_body_tools.py"
LICENSE = "schemas/conform/shared-validators/marketplace-LICENSE"
EMPTY_SHA = "sha256:" + "0" * 64


def load_agent_checker(root=ROOT):
    """Return (callable, manifest hash, reason); never import unchecked bytes."""
    policy_hash = EMPTY_SHA
    try:
        pin, policy_hash = read_json_snapshot(root, PIN)
        if not isinstance(pin, dict) or pin.get("format") != "shared-validator-pin/v1":
            raise UnmeasuredReference("unsupported shared-validator manifest")
        if (pin.get("validator") != "agent-body-tools" or pin.get("license") != "MIT"
                or pin.get("source_path") != "scripts/agent_body_tools.py"
                or pin.get("source_repository") != "https://github.com/jeremylongshore/tons-of-skills-marketplace"
                or not isinstance(pin.get("source_commit"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", pin["source_commit"])):
            raise UnmeasuredReference("shared-validator provenance is incomplete")
        files = pin.get("files")
        if not isinstance(files, dict) or set(files) != {MODULE, LICENSE}:
            raise UnmeasuredReference("shared-validator manifest has unsupported files")
        snapshots = {}
        for path, expected in files.items():
            raw, digest = read_bytes_snapshot(root, path)
            if not isinstance(expected, str) or expected != digest:
                raise UnmeasuredReference("shared-validator file hash mismatch")
            snapshots[path] = raw
        # Compile the exact bytes just hashed, avoiding a second filesystem read
        # or import-cache/cwd substitution between verification and execution.
        namespace = {"__name__": "_audit_harness_pinned_agent_body_tools"}
        exec(compile(snapshots[MODULE], MODULE, "exec"), namespace)
        checker = namespace.get("check_agent_body_vs_allowlist")
        if not callable(checker):
            raise UnmeasuredReference("shared-validator callable is missing")
        return checker, policy_hash, None
    except (InvalidArtifact, UnmeasuredReference) as exc:
        return None, exc.input_hash or policy_hash, str(exc)
    except Exception:
        return None, policy_hash, "shared-validator implementation could not be loaded"


def agent_findings(checker, frontmatter, body):
    """Retain upstream errors and warnings as distinct static findings."""
    try:
        result = checker(frontmatter, body)
        if (not isinstance(result, tuple) or len(result) != 2
                or any(not isinstance(items, list) for items in result)
                or any(not isinstance(item, str) for items in result for item in items)):
            raise ValueError("invalid findings")
        return result[0], result[1], None
    except Exception:
        return [], [], "shared-validator did not return supported findings"


def combined_policy_hash(schema_policy, shared_policy):
    """Keep schema and implementation identity distinct and unambiguous."""
    import json
    raw = json.dumps({"format": "shared-conformance-policy/v1", "schema": schema_policy,
                      "shared_validator": shared_policy}, sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()
