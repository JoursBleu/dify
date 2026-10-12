from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_and_provider_contract() -> None:
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text())
    provider = yaml.safe_load((ROOT / "provider" / "radeon_cloud.yaml").read_text())

    assert manifest["name"] == "radeon_cloud"
    assert manifest["plugins"]["models"] == ["provider/radeon_cloud.yaml"]
    assert manifest["network"]["domains"] == ["developer.amd.com.cn"]
    assert provider["provider"] == "radeon_cloud"
    assert provider["configurate_methods"] == ["predefined-model"]
    credentials = provider["provider_credential_schema"]["credential_form_schemas"]
    assert [field["variable"] for field in credentials] == ["api_key"]
    assert credentials[0]["type"] == "secret-input"
    assert credentials[0]["required"] is True


def test_referenced_files_exist() -> None:
    provider = yaml.safe_load((ROOT / "provider" / "radeon_cloud.yaml").read_text())
    assert (ROOT / provider["extra"]["python"]["provider_source"]).is_file()
    for source in provider["extra"]["python"]["model_sources"]:
        assert (ROOT / source).is_file()