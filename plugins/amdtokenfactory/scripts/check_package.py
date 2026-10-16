"""Check a locally built .difypkg for prohibited files and embedded credential literals."""

import argparse
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

import yaml

PROHIBITED_PARTS = {
    ".git", ".venv", ".venv-dev", ".venv-test", ".pytest_cache", ".ruff_cache",
    "__pycache__", "tests", "scripts", "validation-report",
    "api", "api-compat", "windows-installer",
}
KEY_LITERAL = re.compile(rb"\b(?:rc-|rcsk_|sk-)[A-Za-z0-9_-]{24,}\b")
# dify-plugin-daemon 0.6.10 pkg/entities/plugin_entities/identity.go.
NATIVE_IDENTIFIER = re.compile(
    r"(?:[a-z0-9_-]{1,64}/)?[a-z0-9_-]{1,255}:"
    r"[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}(?:-\w{1,16})?@[a-f0-9]{32,64}",
    re.ASCII,
)


def valid_plugin_identity(manifest: object) -> bool:
    if not isinstance(manifest, dict):
        return False
    author, name, version = (manifest.get(field) for field in ("author", "name", "version"))
    if not all(isinstance(value, str) for value in (author, name, version)):
        return False
    identity = f"{author + '/' if author else ''}{name}:{version}@{'a' * 64}"
    return NATIVE_IDENTIFIER.fullmatch(identity) is not None


def inspect_package(path: Path) -> list[str]:
    failures = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            failures.append("Package contains duplicate entries")
        if "manifest.yaml" in names:
            try:
                manifest = yaml.safe_load(archive.read("manifest.yaml"))
            except yaml.YAMLError:
                manifest = None
            if not valid_plugin_identity(manifest):
                failures.append(
                    "Manifest author/name/version violate the native plugin identifier grammar"
                )
            if not isinstance(manifest, dict) or manifest.get("contact") != "Letian.Kang@amd.com":
                failures.append("Manifest must declare the current integration contact")
            if not isinstance(manifest, dict) or (
                manifest.get("author"), manifest.get("name")
            ) != ("amdtokenfactory", "amdtokenfactory"):
                failures.append("Manifest must use the amdtokenfactory/amdtokenfactory identity")
            if not isinstance(manifest, dict) or manifest.get("version") != "0.0.12":
                failures.append("Manifest must use package version 0.0.12")
            if not isinstance(manifest, dict) or manifest.get("plugins") != {
                "models": ["provider/amdtokenfactory.yaml"]
            }:
                failures.append("Manifest must declare provider/amdtokenfactory.yaml")
        for declaration_path in ("manifest.yaml", "provider/amdtokenfactory.yaml"):
            if declaration_path not in names:
                continue
            try:
                declaration = yaml.safe_load(archive.read(declaration_path))
            except yaml.YAMLError:
                declaration = None
            descriptions = (
                declaration.get("description", {}) if isinstance(declaration, dict) else {}
            )
            if not isinstance(descriptions, dict) or not descriptions or not all(
                isinstance(text, str) and "Letian Kang" in text and "Letian.Kang@amd.com" in text
                for text in descriptions.values()
            ):
                failures.append(f"Missing human author/contact in: {declaration_path}")
            if not isinstance(declaration, dict) or declaration.get("label") != {
                "en_US": "AMDTokenFactory", "zh_Hans": "AMDTokenFactory"
            }:
                failures.append(
                    f"Invalid AMDTokenFactory display label in: {declaration_path}"
                )
            if declaration_path.startswith("provider/") and (
                not isinstance(declaration, dict)
                or declaration.get("provider") != "amdtokenfactory"
            ):
                failures.append("Provider must use the amdtokenfactory identity")
            if declaration_path.startswith("provider/"):
                if not isinstance(declaration, dict) or (
                    declaration.get("remote_model_catalog") is not True
                ):
                    failures.append("Provider must declare remote_model_catalog: true")
                if not isinstance(declaration, dict) or declaration.get("models") != {
                    "llm": {"predefined": []}
                }:
                    failures.append("Provider must use an empty predefined LLM catalog")
                credentials = declaration.get("provider_credential_schema", {}) if (
                    isinstance(declaration, dict)
                ) else {}
                if (
                    not isinstance(declaration, dict)
                    or declaration.get("configurate_methods") != ["predefined-model"]
                    or "model_credential_schema" in declaration
                    or not isinstance(credentials, dict)
                    or not isinstance(forms := credentials.get("credential_form_schemas"), list)
                    or len(forms) != 1
                    or not isinstance(forms[0], dict)
                    or forms[0].get("variable") != "api_key"
                    or forms[0].get("type") != "secret-input"
                    or forms[0].get("required") is not True
                ):
                    failures.append("Provider must use only the unified required API Key form")
                extra = declaration.get("extra") if isinstance(declaration, dict) else None
                python = extra.get("python") if isinstance(extra, dict) else None
                if not isinstance(python, dict) or python.get("provider_source") != (
                    "provider/amdtokenfactory.py"
                ):
                    failures.append("Provider must declare provider/amdtokenfactory.py")
        obsolete_sources = (
            "provider/amdgpucloud.yaml", "provider/amdgpucloud.py",
            "provider/radeon_cloud.yaml", "provider/radeon_cloud.py",
        )
        if any(name in names for name in obsolete_sources):
            failures.append("Package includes the obsolete provider identity")
        for relative in ("manifest.yaml", "provider/amdtokenfactory.yaml",
                         "provider/amdtokenfactory.py"):
            if relative not in names:
                continue
            source = archive.read(relative).decode("utf-8").lower()
            if any(
                old_name in source for old_name in ("amdgpucloud", "radeon_cloud", "radeoncloud")
            ):
                failures.append(f"Obsolete provider source reference in: {relative}")
        for item in archive.infolist():
            entry = PurePosixPath(item.filename)
            if (
                entry.is_absolute()
                or ".." in entry.parts
                or PROHIBITED_PARTS.intersection(entry.parts)
                or entry.name.startswith(".env")
                or entry.suffix in {".pyc", ".pyo", ".log", ".difypkg"}
                or entry.name in {"amdtokenfactory_remote.py", "amdgpucloud_remote.py"}
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.file_size > 2 * 1024 * 1024
            ):
                failures.append(f"Prohibited package entry: {item.filename}")
                continue
            if not item.is_dir() and KEY_LITERAL.search(archive.read(item)):
                failures.append(f"Possible credential literal in: {item.filename}")
        for required in (
            "manifest.yaml", "provider/amdtokenfactory.yaml", "provider/amdtokenfactory.py",
            "models/llm/llm.py",
            "model_catalog.py", "models/_catalog.py", "models/_credentials.py",
            "models/_transport.py", "PRIVACY.md", "README.md",
            "readme/README_zh_Hans.md", "readme/INSTALL_windows_zh_Hans.txt",
        ):
            if required not in names:
                failures.append(f"Missing package entry: {required}")
        if any(name.startswith("models/llm/") and name.endswith(".yaml") for name in names):
            failures.append("Remote-discovery package must not embed a static model catalog")
        for relative in (
            "README.md", "PRIVACY.md", "readme/README_zh_Hans.md",
            "readme/INSTALL_windows_zh_Hans.txt",
        ):
            if relative not in names:
                continue
            text = archive.read(relative).decode("utf-8")
            if "Letian Kang" not in text or "Letian.Kang@amd.com" not in text:
                failures.append(f"Missing human author/contact in: {relative}")
            if "kangletian@hotmail.com" in text:
                failures.append(f"Obsolete public contact in: {relative}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    failures = inspect_package(parser.parse_args().package)
    for failure in failures:
        print(failure)
    print(f"Package safety audit: {len(failures)} failure(s)")
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())