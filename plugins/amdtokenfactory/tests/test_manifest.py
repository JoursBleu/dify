import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from scripts.check_package import valid_plugin_identity

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_and_provider_contract() -> None:
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text())
    provider = yaml.safe_load((ROOT / "provider" / "amdtokenfactory.yaml").read_text())

    assert manifest["name"] == "amdtokenfactory"
    assert manifest["label"] == {"en_US": "AMDTokenFactory", "zh_Hans": "AMDTokenFactory"}
    assert manifest["author"] == "amdtokenfactory"
    assert manifest["version"] == "0.0.12"
    assert manifest["meta"]["version"] == "0.0.2"
    assert manifest["meta"]["minimum_dify_version"] == "1.17.1"
    assert manifest["plugins"]["models"] == ["provider/amdtokenfactory.yaml"]
    assert manifest["network"]["domains"] == ["developer.amd.com.cn"]
    assert provider["provider"] == "amdtokenfactory"
    plugin_id = f'{manifest["author"]}/{manifest["name"]}'
    assert plugin_id == "amdtokenfactory/amdtokenfactory"
    assert f'{plugin_id}/{provider["provider"]}' == (
        "amdtokenfactory/amdtokenfactory/amdtokenfactory"
    )
    assert provider["label"] == manifest["label"]
    assert provider["extra"]["python"] == {
        "provider_source": "provider/amdtokenfactory.py",
        "model_sources": ["models/llm/llm.py"],
    }
    assert provider["configurate_methods"] == ["predefined-model"]
    assert provider["remote_model_catalog"] is True
    assert "model_credential_schema" not in provider
    credentials = provider["provider_credential_schema"]["credential_form_schemas"]
    assert [field["variable"] for field in credentials] == ["api_key"]
    assert credentials[0]["type"] == "secret-input"
    assert credentials[0]["required"] is True


def test_get_key_help_matches_cherry_service_without_borrowing_its_source() -> None:
    provider = yaml.safe_load((ROOT / "provider" / "amdtokenfactory.yaml").read_text())
    for url in provider["help"]["url"].values():
        assert url == "https://developer.amd.com.cn/radeon/modelapis"
        assert urlsplit(url).query == ""


def test_brand_icon_is_local_and_shared_by_the_native_provider() -> None:
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text())
    provider = yaml.safe_load((ROOT / "provider" / "amdtokenfactory.yaml").read_text())
    assert manifest["icon"] == "icon.png"
    icon = (ROOT / "_assets" / manifest["icon"]).read_bytes()
    assert icon[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(icon[16:20], "big") == 256
    assert int.from_bytes(icon[20:24], "big") == 256
    for size in ("icon_small", "icon_large"):
        assert set(provider[size].values()) == {"icon.png"}


def test_referenced_files_exist() -> None:
    provider = yaml.safe_load((ROOT / "provider" / "amdtokenfactory.yaml").read_text())
    assert (ROOT / provider["extra"]["python"]["provider_source"]).is_file()
    for source in provider["extra"]["python"]["model_sources"]:
        assert (ROOT / source).is_file()


def test_manifest_identity_matches_native_daemon_grammar() -> None:
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text())
    assert valid_plugin_identity(manifest)


def test_native_identifier_rejects_mixed_case_author() -> None:
    assert not valid_plugin_identity(
        {"author": "Letian-Kang", "name": "amdtokenfactory", "version": "0.0.10"}
    )
    assert valid_plugin_identity(
        {"author": "letian-kang", "name": "amdtokenfactory", "version": "0.0.10"}
    )


def test_personal_publisher_uses_hyphen_not_unsupported_dot() -> None:
    assert not valid_plugin_identity(
        {"author": "letian.kang", "name": "amdtokenfactory", "version": "0.0.10"}
    )
    assert valid_plugin_identity(
        {"author": "letian-kang", "name": "amdtokenfactory", "version": "0.0.10"}
    )


def test_human_author_and_contact_are_consistent_without_breaking_identity() -> None:
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text())
    provider = yaml.safe_load((ROOT / "provider/amdtokenfactory.yaml").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert manifest["author"] == "amdtokenfactory"
    assert manifest["name"] == provider["provider"] == "amdtokenfactory"
    assert project["name"] == "dify-plugin-amdtokenfactory"
    assert valid_plugin_identity(manifest)
    assert manifest["contact"] == "Letian.Kang@amd.com"
    assert project["authors"] == [{"name": "Letian Kang", "email": "Letian.Kang@amd.com"}]
    assert project["version"] == manifest["version"]
    for declaration in (manifest, provider):
        assert all(
            "Letian Kang" in text and "Letian.Kang@amd.com" in text
            for text in declaration["description"].values()
        )
    for relative in (
        "README.md", "PRIVACY.md", "readme/README_zh_Hans.md",
        "readme/INSTALL_windows_zh_Hans.txt",
    ):
        text = (ROOT / relative).read_text()
        assert "Letian Kang" in text and "Letian.Kang@amd.com" in text
        assert "kangletian@hotmail.com" not in text


def test_packaged_windows_guide_documents_unreleased_native_setup_without_overlay() -> None:
    guide = (ROOT / "readme/INSTALL_windows_zh_Hans.txt").read_text()
    assert "UNRELEASED" in guide
    assert all(component in guide for component in ("SDK", "daemon", "Dify", "Graphon"))
    assert "api-compat/" not in guide
    assert "windows-installer/" not in guide
    assert "从本地文件" in guide
    assert "amdtokenfactory/amdtokenfactory/amdtokenfactory" in guide
    assert "AMDTokenFactory-0.0.12.difypkg" in guide
    assert "不提供 overlay 部署步骤" in guide
    assert "没有本供应商可选模型" in guide


def test_release_declarations_never_use_the_previous_machine_identity() -> None:
    for relative in (
        "manifest.yaml", "provider/amdtokenfactory.yaml", "provider/amdtokenfactory.py",
        "pyproject.toml",
    ):
        content = (ROOT / relative).read_text()
        assert "amdgpucloud" not in content.lower()
        assert "radeon_cloud" not in content
        assert "joursbleu" not in content
    assert not (ROOT / "provider/amdgpucloud.yaml").exists()
    assert not (ROOT / "provider/amdgpucloud.py").exists()
    assert not (ROOT / "provider/radeon_cloud.yaml").exists()
    assert not (ROOT / "provider/radeon_cloud.py").exists()


def test_remote_catalog_does_not_embed_model_ids_or_fallback_yaml() -> None:
    provider = yaml.safe_load((ROOT / "provider/amdtokenfactory.yaml").read_text())
    assert provider["models"]["llm"]["predefined"] == []
    assert not list((ROOT / "models/llm").glob("*.yaml"))
    assert "VALIDATION_MODEL" not in (ROOT / "models/_credentials.py").read_text()


def test_lock_project_identity_and_version_match_without_dependency_renames() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    local = [package for package in lock["package"] if package.get("source") == {"virtual": "."}]
    assert len(local) == 1
    assert local[0]["name"] == project["name"] == "dify-plugin-amdtokenfactory"
    assert local[0]["version"] == project["version"] == "0.0.12"
    assert local[0]["dependencies"] == [{"name": "dify-plugin"}, {"name": "requests"}]


def test_install_guides_warn_that_prior_identity_cannot_migrate_saved_credentials() -> None:
    for relative in ("README.md", "readme/README_zh_Hans.md", "readme/INSTALL_windows_zh_Hans.txt"):
        text = (ROOT / relative).read_text()
        assert "amdtokenfactory/amdtokenfactory/amdtokenfactory" in text
        assert "amdgpucloud/amdgpucloud" in text  # Historical ID, not a same-ID upgrade promise.
        if relative == "README.md":
            assert "saved credentials cannot migrate automatically" in text
            assert "Do not uninstall the old provider or copy saved keys" in text
            assert "same-ID upgrades" not in text
        else:
            assert "已保存凭据不能自动迁移" in text
            assert "不要卸载旧供应商或复制已保存 Key" in text
            assert "同 ID 升级保留" not in text


def test_all_guides_disclose_paired_rpc_and_stock_sdk_limitations() -> None:
    for relative in ("README.md", "readme/README_zh_Hans.md", "readme/INSTALL_windows_zh_Hans.txt"):
        text = (ROOT / relative).read_text()
        for required in (
            "0.0.12", "UNRELEASED", "SDK", "daemon", "Dify", "Graphon", "1.17.1", "0.10.2",
            "remote_model_catalog: true", "get_ai_model_list", "fetch_models", "models",
        ):
            assert required in text
        assert "api-compat/" not in text
        assert "publication-only copy" not in text
        assert "本次只改文档" not in text