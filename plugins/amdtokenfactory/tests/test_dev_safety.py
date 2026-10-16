import zipfile
from pathlib import Path

import pytest
import yaml

from scripts.check_package import inspect_package
from scripts.run_live_tests import load_private_key


def test_live_launcher_requires_private_owned_regular_key_file(tmp_path: Path) -> None:
    path = tmp_path / "test-key"
    path.write_text("rc-offline-fixture")
    path.chmod(0o600)
    assert load_private_key(path) == "rc-offline-fixture"
    path.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        load_private_key(path)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="0600"):
        load_private_key(link)


def test_package_audit_rejects_environment_traversal_and_credential_literals(tmp_path) -> None:
    package = tmp_path / "unsafe.difypkg"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(".env", "not-a-secret")
        archive.writestr(".venv-dev/file", "not-a-secret")
        archive.writestr("../escape", "not-a-secret")
        archive.writestr("literal.py", "rc-" + "x" * 48)
    failures = inspect_package(package)
    assert any(".env" in failure for failure in failures)
    assert any(".venv-dev" in failure for failure in failures)
    assert any("../escape" in failure for failure in failures)
    assert any("Possible credential literal" in failure for failure in failures)


@pytest.mark.parametrize(
    "relative", ["provider/amdtokenfactory.yaml", "readme/INSTALL_windows_zh_Hans.txt"]
)
def test_package_audit_rejects_missing_human_author_and_contact(
    tmp_path: Path, relative: str
) -> None:
    root = Path(__file__).resolve().parents[1]
    package = tmp_path / "missing-attribution.difypkg"
    with zipfile.ZipFile(package, "w") as archive:
        for name in (
            "manifest.yaml", "provider/amdtokenfactory.yaml", "models/llm/llm.py",
            "models/_transport.py", "PRIVACY.md", "README.md", "readme/README_zh_Hans.md",
            "readme/INSTALL_windows_zh_Hans.txt",
        ):
            text = (root / name).read_text()
            if name == relative:
                text = text.replace("Letian Kang", "Previous maintainer").replace(
                    "Letian.Kang@amd.com", "kangletian@hotmail.com"
                )
            archive.writestr(name, text)
    failures = inspect_package(package)
    assert any(f"Missing human author/contact in: {relative}" == failure for failure in failures)


@pytest.mark.parametrize("field,old_value", [
    ("author", "joursbleu"), ("name", "radeon_cloud"),
    ("author", "amdgpucloud"), ("name", "amdgpucloud"),
])
def test_package_audit_rejects_display_only_rename_with_old_identity(
    tmp_path, field, old_value
) -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / "manifest.yaml").read_text())
    manifest[field] = old_value
    package = tmp_path / "old-identity.difypkg"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("manifest.yaml", yaml.safe_dump(manifest))
    assert "Manifest must use the amdtokenfactory/amdtokenfactory identity" in inspect_package(
        package
    )


def test_package_audit_rejects_unrequested_personal_publisher(tmp_path) -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / "manifest.yaml").read_text())
    manifest["author"] = "letian-kang"
    package = tmp_path / "brand-publisher.difypkg"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("manifest.yaml", yaml.safe_dump(manifest))
    assert "Manifest must use the amdtokenfactory/amdtokenfactory identity" in inspect_package(
        package
    )


def _write_current_package(
    path: Path, overrides: dict[str, str] | None = None, *, omit: str = ""
) -> None:
    root = Path(__file__).resolve().parents[1]
    overrides = overrides or {}
    with zipfile.ZipFile(path, "w") as archive:
        for name in (
            "manifest.yaml", "provider/amdtokenfactory.yaml", "provider/amdtokenfactory.py",
            "models/llm/llm.py", "model_catalog.py", "models/_catalog.py",
            "models/_credentials.py", "models/_transport.py", "PRIVACY.md", "README.md",
            "readme/README_zh_Hans.md", "readme/INSTALL_windows_zh_Hans.txt",
        ):
            if name == omit:
                continue
            archive.writestr(name, overrides.get(name, (root / name).read_text()))


def test_package_audit_accepts_current_identity_version_labels_and_sources(tmp_path: Path) -> None:
    package = tmp_path / "AMDTokenFactory-0.0.12.difypkg"
    _write_current_package(package)
    assert inspect_package(package) == []


@pytest.mark.parametrize("relative", [
    "provider/amdgpucloud.yaml", "provider/amdgpucloud.py",
    "provider/radeon_cloud.yaml", "provider/radeon_cloud.py",
])
def test_package_audit_rejects_historical_provider_source_entries(tmp_path, relative) -> None:
    package = tmp_path / "obsolete-source.difypkg"
    _write_current_package(package)
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr(relative, "historical provider source")
    assert "Package includes the obsolete provider identity" in inspect_package(package)


@pytest.mark.parametrize("relative,old_reference", [
    ("manifest.yaml", "provider/amdgpucloud.yaml"),
    ("provider/amdtokenfactory.yaml", "provider/amdgpucloud.py"),
    ("provider/amdtokenfactory.py", "AMDGPUCloudModelProvider"),
])
def test_package_audit_rejects_residual_historical_provider_references(
    tmp_path, relative, old_reference
) -> None:
    root = Path(__file__).resolve().parents[1]
    content = (root / relative).read_text() + f"\n# Historical reference: {old_reference}\n"
    package = tmp_path / "residual-source.difypkg"
    _write_current_package(package, {relative: content})
    assert f"Obsolete provider source reference in: {relative}" in inspect_package(package)


@pytest.mark.parametrize("relative,field,value,expected", [
    ("manifest.yaml", "version", "0.0.11", "Manifest must use package version 0.0.12"),
    ("manifest.yaml", "label", {"en_US": "AMDGPUCloud", "zh_Hans": "AMDGPUCloud"},
     "Invalid AMDTokenFactory display label in: manifest.yaml"),
    ("provider/amdtokenfactory.yaml", "provider", "amdgpucloud",
     "Provider must use the amdtokenfactory identity"),
    ("provider/amdtokenfactory.yaml", "label", {"en_US": "AMDGPUCloud", "zh_Hans": "AMDGPUCloud"},
     "Invalid AMDTokenFactory display label in: provider/amdtokenfactory.yaml"),
    ("manifest.yaml", "plugins", {"models": ["provider/amdgpucloud.yaml"]},
     "Manifest must declare provider/amdtokenfactory.yaml"),
    ("provider/amdtokenfactory.yaml", "extra", {"python": {
        "provider_source": "provider/amdgpucloud.py", "model_sources": ["models/llm/llm.py"],
    }}, "Provider must declare provider/amdtokenfactory.py"),
])
def test_package_audit_rejects_previous_release_contract_values(
    tmp_path, relative, field, value, expected
) -> None:
    root = Path(__file__).resolve().parents[1]
    declaration = yaml.safe_load((root / relative).read_text())
    declaration[field] = value
    package = tmp_path / "previous-contract.difypkg"
    _write_current_package(package, {relative: yaml.safe_dump(declaration)})
    assert expected in inspect_package(package)


def test_package_audit_requires_credentials_runtime_module(tmp_path) -> None:
    package = tmp_path / "missing-runtime-fixture.zip"
    _write_current_package(package, omit="models/_credentials.py")
    assert inspect_package(package) == ["Missing package entry: models/_credentials.py"]


@pytest.mark.parametrize("relative", [
    "api/core/provider_manager.py", "api-compat/catalog.py", "amdtokenfactory_remote.py",
    "amdgpucloud_remote.py", "windows-installer/setup.py",
])
def test_package_audit_rejects_host_api_or_installer_sources(tmp_path, relative) -> None:
    package = tmp_path / "host-source-fixture.zip"
    _write_current_package(package)
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr(relative, "fixture host source")
    assert f"Prohibited package entry: {relative}" in inspect_package(package)


@pytest.mark.parametrize("field,value,expected", [
    ("remote_model_catalog", False, "Provider must declare remote_model_catalog: true"),
    ("remote_model_catalog", "true", "Provider must declare remote_model_catalog: true"),
    ("models", {"llm": {"predefined": ["fixture.yaml"]}},
     "Provider must use an empty predefined LLM catalog"),
    ("model_credential_schema", {}, "Provider must use only the unified required API Key form"),
    ("configurate_methods", ["customizable-model"],
     "Provider must use only the unified required API Key form"),
])
def test_package_audit_enforces_native_catalog_without_manual_model_forms(
    tmp_path, field, value, expected
) -> None:
    root = Path(__file__).resolve().parents[1]
    relative = "provider/amdtokenfactory.yaml"
    declaration = yaml.safe_load((root / relative).read_text())
    declaration[field] = value
    package = tmp_path / "catalog-contract-fixture.zip"
    _write_current_package(package, {relative: yaml.safe_dump(declaration)})
    assert expected in inspect_package(package)