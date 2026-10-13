"""Create a Windows-friendly ZIP from a previously audited plugin and documentation."""

import argparse
import hashlib
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    source = arguments.directory.resolve()
    files = sorted(path for path in source.iterdir() if path.is_file())
    if any(path.is_symlink() for path in files):
        raise ValueError("Delivery files must not be symlinks")
    expected = {}
    for line in (source / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest
    if {path.name for path in files} != {*expected, "SHA256SUMS.txt"}:
        raise ValueError("Delivery directory does not match the audited file list")
    for name, digest in expected.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Delivery checksum mismatch: {name}")
    with zipfile.ZipFile(arguments.output, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=f"{source.name}/{path.name}")
    with zipfile.ZipFile(arguments.output) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        for name, digest in expected.items():
            content = archive.read(f"{source.name}/{name}")
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError(f"ZIP checksum mismatch: {name}")
    output = arguments.output
    print(f"Created: {output}")
    print(f"Size: {output.stat().st_size} bytes")
    print(f"SHA-256: {hashlib.sha256(output.read_bytes()).hexdigest()}")
    print(f"Verified: {len(files)} files, archive CRC and delivery SHA-256 hashes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())