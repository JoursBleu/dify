import base64
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "payload"
TEST_HOME: Path


@pytest.fixture(autouse=True)
def synthetic_configuration(tmp_path: Path) -> None:
    """Parse only a temporary public-template fixture; never read a user's .env."""
    global TEST_HOME
    TEST_HOME = tmp_path
    directory = tmp_path / "app/docker"
    shutil.copytree(PAYLOAD / "docker", directory)
    shutil.copyfile(PAYLOAD / "windows/local.override.yaml", directory / "local.override.yaml")
    values = {
        "SECRET_KEY": "1" * 64,
        "DB_PASSWORD": "synthetic-db-password",
        "REDIS_PASSWORD": "synthetic-redis-password",
        "CELERY_BROKER_URL": "redis://:synthetic-redis-password@redis:6379/1",
        "WEAVIATE_API_KEY": "synthetic-weaviate-password",
        "WEAVIATE_AUTHENTICATION_APIKEY_ALLOWED_KEYS": "synthetic-weaviate-password",
        "WEAVIATE_AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED": "false",
        "CODE_EXECUTION_API_KEY": "synthetic-sandbox-password",
        "SANDBOX_API_KEY": "synthetic-sandbox-password",
        "PLUGIN_DAEMON_KEY": "synthetic-plugin-password",
        "PLUGIN_DIFY_INNER_API_KEY": "synthetic-inner-password",
        "DIFY_AGENT_API_TOKEN": "synthetic-agent-password",
        "DIFY_AGENT_SERVER_SECRET_KEY": base64.urlsafe_b64encode(b"0" * 32).decode().rstrip("="),
        "DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN": "synthetic-local-sandbox-password",
        "EXPOSE_NGINX_PORT": "18081",
        "EXPOSE_PLUGIN_DEBUGGING_PORT": "15003",
        "CONSOLE_API_URL": "",
        "APP_API_URL": "",
        "CONSOLE_CORS_ALLOW_ORIGINS": "http://localhost:18081,http://127.0.0.1:18081",
        "WEB_API_CORS_ALLOW_ORIGINS": "http://localhost:18081,http://127.0.0.1:18081",
        "FORCE_VERIFYING_SIGNATURE": "true",
        "COMPOSE_PROFILES": "postgresql,weaviate,collaboration",
        "DB_TYPE": "postgresql",
        "VECTOR_STORE": "weaviate",
    }
    lines = (PAYLOAD / "docker/.env.example").read_text().splitlines()
    fixture = []
    for line in lines:
        name = line.split("=", 1)[0]
        fixture.append(f"{name}={values[name]}" if name in values else line)
    configuration = directory / ".env"
    configuration.write_text("\n".join(fixture) + "\n")
    configuration.chmod(0o600)


def compose_config() -> dict:
    result = subprocess.run(
        [
            str(PAYLOAD / "tools/docker-compose-linux-x86_64"),
            "--project-name", "dify-windows-test",
            "--project-directory", str(TEST_HOME / "app/docker"),
            "--env-file", str(TEST_HOME / "app/docker/.env"),
            "-f", str(TEST_HOME / "app/docker/docker-compose.yaml"),
            "-f", str(TEST_HOME / "app/docker/local.override.yaml"),
            "config", "--format", "json",
        ],
        env={**os.environ, "COMPOSE_PROFILES": "postgresql,weaviate,collaboration"},
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def test_full_platform_services_and_localhost_ports() -> None:
    config = compose_config()
    expected = {
        "api", "api_websocket", "worker", "worker_beat", "web", "plugin_daemon",
        "agent_backend", "local_sandbox", "sandbox", "ssrf_proxy", "agent_ssrf_proxy",
        "db_postgres", "redis", "weaviate", "nginx", "init_permissions",
    }
    assert expected <= config["services"].keys()
    ports = {
        (name, entry["host_ip"], entry["published"], entry["target"])
        for name, service in config["services"].items()
        if name in expected
        for entry in service.get("ports", [])
    }
    assert ports == {
        ("nginx", "127.0.0.1", "18081", 80),
        ("plugin_daemon", "127.0.0.1", "15003", 5003),
    }
    for name in expected - {"init_permissions"}:
        service = config["services"][name]
        assert service["restart"] == "unless-stopped"
        assert not service.get("privileged")
        assert "docker.sock" not in json.dumps(service.get("volumes", []))


def test_secret_pairs_and_signature_policy() -> None:
    config = compose_config()["services"]
    api = config["api"]["environment"]
    daemon = config["plugin_daemon"]["environment"]
    agent = config["agent_backend"]["environment"]
    assert len(api["SECRET_KEY"]) == 64
    assert api["DB_PASSWORD"] != "difyai123456"
    assert api["REDIS_PASSWORD"] in api["CELERY_BROKER_URL"]
    assert api["CODE_EXECUTION_API_KEY"] == config["sandbox"]["environment"]["API_KEY"]
    assert api["PLUGIN_DAEMON_KEY"] == daemon["SERVER_KEY"]
    assert daemon["SERVER_KEY"] == agent["DIFY_AGENT_PLUGIN_DAEMON_API_KEY"]
    assert daemon["DIFY_INNER_API_KEY"] == agent["DIFY_AGENT_INNER_API_KEY"]
    assert api["INNER_API_KEY_FOR_PLUGIN"] == daemon["DIFY_INNER_API_KEY"]
    assert api["AGENT_BACKEND_API_TOKEN"] == agent["DIFY_AGENT_API_TOKEN"]
    encoded_secret = agent["DIFY_AGENT_SERVER_SECRET_KEY"]
    assert "=" not in encoded_secret
    assert len(base64.urlsafe_b64decode(encoded_secret + "=")) == 32
    assert config["local_sandbox"]["environment"]["SHELLCTL_AUTH_TOKEN"] == agent[
        "DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN"
    ]
    assert daemon["FORCE_VERIFYING_SIGNATURE"] == "true"
    assert config["local_sandbox"]["environment"]["SHELLCTL_ENABLE_PATH_ISOLATION"] == "true"
    assert config["weaviate"]["environment"]["AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED"] == "false"
    assert (TEST_HOME / "app/docker/.env").stat().st_mode & 0o077 == 0


def test_browser_api_configuration_is_same_origin() -> None:
    config = compose_config()["services"]
    assert config["web"]["environment"]["CONSOLE_API_URL"] == ""
    assert config["web"]["environment"]["APP_API_URL"] == ""
    assert config["api"]["environment"]["CONSOLE_CORS_ALLOW_ORIGINS"] == (
        "http://localhost:18081,http://127.0.0.1:18081"
    )


@pytest.mark.parametrize("port,allow", [("80", "false"), ("abc", "false"), ("18080", "invalid")])
def test_invalid_arguments_fail_before_docker_actions(port: str, allow: str) -> None:
    result = subprocess.run(
        ["bash", str(PAYLOAD / "windows/runtime.sh"), "check", port, allow],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "ERROR:" in result.stderr


def test_bundled_runtime_and_plugin_hashes() -> None:
    expected = {
        "tools/docker-compose-linux-x86_64":
            "40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a",
        "plugins/amdgpucloud.difypkg":
            "66f7bd9c8e15136a57228088daa647953d0a373a430d85ee11abff9c5bc5e845",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((PAYLOAD / relative).read_bytes()).hexdigest() == digest


def test_install_script_never_removes_volumes_or_bypasses_system_security() -> None:
    script = (PAYLOAD / "windows/runtime.sh").read_text()
    for forbidden in ("down -v", "prune", "rm -rf", "sudo ", "wsl --unregister"):
        assert forbidden not in script
    assert "flock -n 9" in script
    assert "verify_existing" in script
    assert 'unix:///var/run/docker.sock' in script


def test_plugin_management_uses_native_page_without_installation_side_effects() -> None:
    source = (ROOT / "DifySetup.cs").read_text()
    assert 'AddButton("插件管理"' in source
    assert 'AddButton("Radeon 插件"' not in source
    assert 'ShowPlugin' not in source
    assert 'return LocalOrigin(port) + "/integrations";' in source
    handler = source.split("private void OpenIntegrations()", 1)[1].split(
        "private void Append", 1
    )[0]
    assert "navigate(Program.IntegrationsUrl(Decimal.ToInt32(port.Value)));" in handler
    for forbidden in ("InstallFiles", "MessageBox", "Extract", "unsigned.", "RunLogged"):
        assert forbidden not in handler


def test_native_self_test_clicks_management_for_both_ports_without_file_changes() -> None:
    source = (ROOT / "DifySetup.cs").read_text()
    assert 'new InstallerForm(null, delegate(string target) { navigation = target; })' in source
    assert 'new[] { 18080, 18082 }' in source
    assert 'onClick.Invoke(management, new object[] { EventArgs.Empty });' in source
    assert "navigation != IntegrationsUrl(testPort)" in source
    assert "filesBefore.Count != filesAfter.Count" in source


def test_author_and_contact_cover_installer_metadata_ui_and_all_documents() -> None:
    source = (ROOT / "DifySetup.cs").read_text()
    assert '[assembly: AssemblyCompany("Letian Kang")]' in source
    assert '[assembly: AssemblyMetadata("Contact", "Letian.Kang@amd.com")]' in source
    assert 'Text = Program.IntegrationAttribution' in source
    for relative in (
        "安装说明.txt", "THIRD_PARTY_NOTICES.txt", "plugins/INSTALL_windows_zh_Hans.txt",
        "plugins/README_zh_Hans.md", "plugins/PRIVACY.md",
    ):
        text = (PAYLOAD / relative).read_text()
        assert "Letian Kang" in text and "Letian.Kang@amd.com" in text
        assert "kangletian@hotmail.com" not in text


def test_windows_payload_contains_only_the_branded_machine_identity() -> None:
    assert not (PAYLOAD / "plugins/radeon_cloud.difypkg").exists()
    with zipfile.ZipFile(PAYLOAD / "plugins/amdgpucloud.difypkg") as archive:
        manifest = yaml.safe_load(archive.read("manifest.yaml"))
        provider = yaml.safe_load(archive.read("provider/amdgpucloud.yaml"))
        assert manifest["author"] == "letian-kang"
        assert manifest["name"] == provider["provider"] == "amdgpucloud"
        assert manifest["label"] == provider["label"] == {
            "en_US": "AMDGPUCloud", "zh_Hans": "AMDGPUCloud"
        }
        assert "provider/radeon_cloud.yaml" not in archive.namelist()
    source = (ROOT / "DifySetup.cs").read_text()
    assert "Plugin identity must be letian-kang/amdgpucloud" in source


def test_configuration_fixture_is_not_an_installed_user_directory() -> None:
    assert ".local/share" not in str(TEST_HOME)
    assert "synthetic-plugin-password" in (TEST_HOME / "app/docker/.env").read_text()