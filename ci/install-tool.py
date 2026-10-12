#!/usr/bin/env python3
"""Install a hash-pinned CI archive member; verify before extracting or executing."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import tarfile
import tempfile
from urllib.request import urlopen

LIMIT = 64 * 1024 * 1024


def install(pin, tool, destination, opener=urlopen):
    with opener(pin["url"], timeout=60) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT or hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("archive size or SHA256 verification failed")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        member = archive.getmember(pin["member"])
        if not member.isfile() or member.size > LIMIT:
            raise ValueError("pinned archive member is not a bounded regular file")
        # Read exactly one member; never unpack archive-supplied filesystem paths.
        with archive.extractfile(member) as source:
            binary = source.read(LIMIT + 1)
    if not binary or len(binary) > LIMIT:
        raise ValueError("archive member has invalid size")
    destination.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as output:
            temporary = Path(output.name)
            output.write(binary)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o755)
        os.replace(temporary, destination / tool)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    pins = json.loads(Path(__file__).with_name("downloads.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=sorted(pins))
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        parser.error("pinned CI archives support Linux x86_64 only")
    try:
        install(pins[args.tool], args.tool, args.destination)
    except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
        parser.exit(1, f"install-tool: verification/install failed: {exc}\n")
    print(f"install-tool: verified {args.tool} {pins[args.tool]['version']}")


if __name__ == "__main__":
    main()
