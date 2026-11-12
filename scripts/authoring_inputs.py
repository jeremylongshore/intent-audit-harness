"""Read bounded JSON artifact snapshots beneath an explicit repository root.

No network, environment expansion, archive extraction or executable evaluation.
Reference declarations outside this supported local JSON surface are reported
as unmeasured, not accepted as kernel-conformant.
"""

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 128


class UnmeasuredReference(ValueError):
    """This reader cannot establish conformance for the declaration."""

    def __init__(self, message, input_hash=None):
        super().__init__(message)
        self.input_hash = input_hash


class InvalidArtifact(ValueError):
    """Artifact bytes are present but not an unambiguous JSON document."""

    def __init__(self, message, input_hash=None):
        super().__init__(message)
        self.input_hash = input_hash


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidArtifact("artifact contains duplicate JSON object keys")
        result[key] = value
    return result


def invalid_constant(_value):
    raise InvalidArtifact("artifact contains a non-JSON numeric constant")


def bounded_depth(data):
    """Do not depend on interpreter-specific JSON decoder recursion limits."""
    pending = [(data, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise UnmeasuredReference("artifact exceeds JSON nesting limit")
        if isinstance(value, dict):
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)


def reference_path(reference):
    """Resolve only the documented ./ local JSON syntax, without filesystem IO."""
    if not isinstance(reference, str) or not reference.startswith("./"):
        raise UnmeasuredReference("reference must be an explicit ./ local JSON path")
    parts = reference[2:].split("/")
    if any(part in ("", ".", "..") for part in parts) or "\\" in reference or "\0" in reference:
        raise UnmeasuredReference("reference contains unsupported path components")
    if PurePosixPath(reference).suffix != ".json":
        raise UnmeasuredReference("only local JSON references are measured; bundles are unsupported")
    return "/".join(parts)


def read_bytes_snapshot(root, relative_path):
    """Bind bytes and digest to one read, refusing symlinks and special files.

    Each path component is opened relative to the preceding directory descriptor.
    Platforms without the required no-follow/directory primitives fail explicitly.
    Callers can retain the digest without printing arbitrary configuration values.
    """
    parts = relative_path.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts) or "\\" in relative_path:
        raise UnmeasuredReference("artifact path must be confined and relative")
    if not all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")):
        raise UnmeasuredReference("safe artifact reader is unavailable on this platform")
    descriptors = []
    try:
        directory = os.open(Path(root).resolve(), os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(directory)
        for part in parts[:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            descriptors.append(directory)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON_BYTES:
            raise UnmeasuredReference("artifact must be a bounded regular JSON file")
        chunks = []
        remaining = MAX_JSON_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_JSON_BYTES:
            raise UnmeasuredReference("artifact exceeded JSON size limit while reading")
        return raw, "sha256:" + hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError) as exc:
        if isinstance(exc, (UnmeasuredReference, InvalidArtifact)):
            raise
        raise UnmeasuredReference("artifact could not be safely opened") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def read_json_snapshot(root, relative_path):
    raw, digest = read_bytes_snapshot(root, relative_path)
    try:
        data = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        bounded_depth(data)
    except (RecursionError, UnmeasuredReference) as exc:
        raise UnmeasuredReference("artifact exceeds supported JSON nesting", digest) from exc
    except (ValueError, UnicodeError) as exc:
        raise InvalidArtifact("artifact is not valid unambiguous JSON", digest) from exc
    return data, digest


def read_frontmatter_snapshot(root, relative_path):
    raw, digest = read_bytes_snapshot(root, relative_path)
    try:
        import yaml
    except ImportError as exc:
        raise UnmeasuredReference("PyYAML unavailable for embedded hooks", digest) from exc
    try:
        text = raw.decode("utf-8-sig")
        match = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.DOTALL)
        if not match:
            raise InvalidArtifact("missing or malformed frontmatter", digest)
        frontmatter = match.group(1)
        # Inspect the event stream before constructing objects: aliases can
        # encode cyclic or exponentially traversed graphs in very few bytes.
        depth = 0
        for index, event in enumerate(yaml.parse(frontmatter, Loader=yaml.SafeLoader)):
            if index >= 100000:
                raise UnmeasuredReference("frontmatter exceeds event limit")
            if isinstance(event, yaml.events.AliasEvent):
                raise UnmeasuredReference("frontmatter aliases are not measured")
            if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
                depth += 1
                if depth > MAX_JSON_DEPTH:
                    raise UnmeasuredReference("frontmatter exceeds nesting limit")
            elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
                depth -= 1

        class UniqueLoader(yaml.SafeLoader):
            def construct_mapping(self, node, deep=False):
                result = {}
                for key_node, value_node in node.value:
                    key = self.construct_object(key_node, deep=deep)
                    if not isinstance(key, str):
                        raise InvalidArtifact("frontmatter mapping keys must be strings")
                    if key in result:
                        raise InvalidArtifact("frontmatter contains duplicate mapping keys")
                    result[key] = self.construct_object(value_node, deep=deep)
                return result

        data = yaml.load(frontmatter, Loader=UniqueLoader)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise InvalidArtifact("frontmatter must be a mapping", digest)
        bounded_depth(data)
    except (RecursionError, UnmeasuredReference) as exc:
        raise UnmeasuredReference("frontmatter exceeds supported measurement bounds", digest) from exc
    except (ValueError, UnicodeError, yaml.YAMLError) as exc:
        raise InvalidArtifact("artifact is not valid frontmatter", digest) from exc
    return data, digest
