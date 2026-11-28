"""Opt-in discovery of repository-local embedded authoring declarations.

Discovery reports candidate locations; parsing, schema checks and reference
resolution remain separate. Unreadable candidates are retained for an explicit
unmeasured result rather than silently disappearing from the gate selection.
"""

import os
from pathlib import Path

from authoring_inputs import InvalidArtifact, UnmeasuredReference, read_frontmatter_snapshot, read_json_snapshot

SKIP = {"node_modules", ".git", ".venv", "dist", "build", "fixtures", "tests", "test", "__tests__", "examples"}


def declares_json(root, path, field):
    try:
        data, _ = read_json_snapshot(root, path)
        return isinstance(data, dict) and field in data
    except (InvalidArtifact, UnmeasuredReference):
        return True


def declares_frontmatter_hooks(root, path):
    try:
        data, _ = read_frontmatter_snapshot(root, path)
        return "hooks" in data
    except (InvalidArtifact, UnmeasuredReference):
        return True


def embedded_artifacts(root, kind):
    """Return relative paths/modes; never inspect the operator's home config."""
    root = Path(root)
    field = "mcpServers" if kind == "mcp" else "hooks"
    found = {}
    bases = [Path(".")]
    packages = root / "packages"
    if packages.is_dir() and not packages.is_symlink():
        bases += [Path("packages") / p.name for p in sorted(packages.iterdir())
                  if p.is_dir() and not p.is_symlink() and (p / "package.json").is_file()]
    for base in bases:
        names = [".claude-plugin/plugin.json", "plugin.json"]
        if kind == "mcp":
            names.append("package.json")
        for name in names:
            path = (base / name).as_posix()
            if os.path.lexists(root / path) and declares_json(root, path, field):
                found[path] = "manifest"
    if kind == "hook":
        for path in (".claude/settings.json", ".claude/settings.local.json"):
            if os.path.lexists(root / path) and declares_json(root, path, field):
                found[path] = "settings"
        for directory, dirs, files in os.walk(root, followlinks=False):
            relative = Path(directory).relative_to(root)
            dirs[:] = [d for d in dirs if d not in SKIP and not (Path(directory) / d).is_symlink()]
            if len(relative.parts) >= 4:
                dirs[:] = []
            for name in sorted(files):
                path = (relative / name).as_posix()
                is_agent = name.endswith(".md") and "agents" in relative.parts
                if (name == "SKILL.md" or is_agent) and declares_frontmatter_hooks(root, path):
                    found[path] = "frontmatter"
    return sorted(found.items())
