#!/usr/bin/env python3
"""Check repository-declared CI action and download boundaries, offline."""
import argparse
import json
from pathlib import Path
import re

import yaml


def check_workflow(text):
    errors = []
    lines = text.splitlines()

    def visit(node):
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                if key.value == "uses":
                    use = value.value if isinstance(value, yaml.ScalarNode) else ""
                    line = lines[value.start_mark.line]
                    if not use.startswith("./"):
                        if not re.fullmatch(r"[\w.-]+/[\w./-]+@[a-f0-9]{40}", use):
                            errors.append("external uses must have a full commit SHA")
                        if "#" not in line or not line.split("#", 1)[1].strip():
                            errors.append("external uses must carry a readable version/snapshot comment")
                if key.value == "run" and isinstance(value, yaml.ScalarNode):
                    script = value.value.replace("\\\n", " ")
                    for command in script.splitlines():
                        if command.lstrip().startswith("#"):
                            continue
                        # Outgoing notification POSTs do not install artifacts.
                        for match in re.finditer(r"\b(curl|wget)\b([^;|&]*)", command):
                            if match[1] != "curl" or not re.search(r"-X\s+POST\b", match[2]):
                                errors.append("direct downloads must use the checksum-verifying CI installer")
                        if re.search(r"\bpip\s+install\b", command) and not re.search(
                            r"pip install --require-hashes --only-binary=:all: -r ci/requirements\.txt\s*$", command
                        ):
                            errors.append("Python CI installs must use the hash-locked requirements")
                        if re.search(r"\bnpm\s+(?:i|install)\b|\bgh\s+release\s+download\b", command):
                            errors.append("use a committed lockfile or verified installer, not an unpinned install")
                        if re.search(r"urlopen\(|requests\.get\(|fetch\(|Invoke-WebRequest", command):
                            errors.append("inline network retrieval must move behind a verified installer")
                visit(value)
        elif isinstance(node, yaml.SequenceNode):
            for child in node.value:
                visit(child)

    try:
        node = yaml.compose(text, Loader=yaml.BaseLoader)
        if node is not None:
            visit(node)
    except yaml.YAMLError:
        errors.append("workflow YAML could not be parsed")
    return errors


def check(root):
    errors = []
    workflows = sorted((root / ".github/workflows").glob("*.y*ml"))
    for path in workflows:
        errors.extend(f"{path.relative_to(root)}: {error}" for error in check_workflow(path.read_text()))
    pins = json.loads((root / "ci/downloads.json").read_text())
    for tool, pin in pins.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]*", tool):
            errors.append("invalid CI executable name")
        if not re.fullmatch(r"[a-f0-9]{64}", pin.get("sha256", "")):
            errors.append(f"{tool}: missing archive SHA256")
        if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/releases/download/v[0-9.]+/[^/]+", pin["url"]):
            errors.append(f"{tool}: expected a versioned upstream release URL")
    requirements = (root / "ci/requirements.txt").read_text().splitlines()
    for line in requirements:
        if line and not line.startswith("#") and not re.fullmatch(
            r"[\w.-]+==[\w.+-]+ --hash=sha256:[a-f0-9]{64}", line
        ):
            errors.append("Python requirement lacks an exact version and payload hash")
    package = json.loads((root / "ci/package.json").read_text())
    lock = json.loads((root / "ci/package-lock.json").read_text())
    if package.get("dependencies") != lock["packages"][""].get("dependencies"):
        errors.append("CI npm manifest and lockfile disagree")
    for name, entry in lock["packages"].items():
        if name and (not entry.get("resolved", "").startswith("https://registry.npmjs.org/")
                     or not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", entry.get("integrity", ""))):
            errors.append(f"{name}: missing registry payload integrity")
    if not (root / "tests/fixtures/gate-result-v1.schema.json").is_file():
        errors.append("bundled gate-result schema is missing")
    dependabot = yaml.safe_load((root / ".github/dependabot.yml").read_text())
    coverage = {(entry["package-ecosystem"], entry["directory"]) for entry in dependabot["updates"]}
    for required in (("github-actions", "/"), ("npm", "/ci"), ("pip", "/ci")):
        if required not in coverage:
            errors.append(f"missing Dependabot coverage: {required}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = check(args.root)
    for error in errors:
        print(error)
    if not errors:
        print("CI supply-chain policy: PASS")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
