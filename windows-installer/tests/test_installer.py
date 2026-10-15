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
DIFY_COMMIT = "8387590ace4a094de812b7847fc6a4c3a27cd52b"
TEST_HOME: Path


@pytest.fixture(scope="session", autouse=True)
def prepared_payload() -> set[str]:
    required = (
        ".upstream-commit", ".prepared.sha256", "docker/docker-compose.yaml",
        "docker/.env.example", "plugins/AMDTokenFactory-0.0.10.difypkg",
        "tools/docker-compose-linux-x86_64", "api-compat/prepare_overlay.py",
        "api-compat/model_catalog.py", "api-compat/amdtokenfactory_remote.py",
    )
    if not all(
        (PAYLOAD / relative).is_file()
        and not any(path.is_symlink() for path in (PAYLOAD / relative, *(PAYLOAD / relative).parents))
        for relative in required
    ):
        pytest.fail(
            "Prepare generated inputs first: bash windows-installer/prepare_payload.sh "
            "/absolute/path/to/AMDTokenFactory-0.0.10.difypkg --offline --source-repository PINNED_REPOSITORY "
            "--compose REVIEWED_COMPOSE",
            pytrace=False,
        )
    # Fixed release hashes, not a mutable receipt, authorize test binary inputs.
    for relative, digest in {
        "tools/docker-compose-linux-x86_64":
            "40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a",
        "plugins/AMDTokenFactory-0.0.10.difypkg":
            "a52e0e67f0c152d2d458ac77e4ac4fc189bd69e2d29d81f07b3f2d3555ebb528",
    }.items():
        assert hashlib.sha256((PAYLOAD / relative).read_bytes()).hexdigest() == digest
    assert (PAYLOAD / ".upstream-commit").read_text().rstrip("\r\n") == DIFY_COMMIT
    recorded = set()
    for line in (PAYLOAD / ".prepared.sha256").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        assert all(part not in ("", ".", "..", ".env") for part in relative.split("/"))
        assert not any(character in relative for character in '\\:\n\r\t*?"<>|')
        assert relative not in recorded
        source = PAYLOAD / relative
        assert source.is_file()
        assert not any(path.is_symlink() for path in (source, *source.parents))
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        recorded.add(relative)
    assert set(required) - {".upstream-commit", ".prepared.sha256"} <= recorded
    return recorded


@pytest.fixture(autouse=True)
def synthetic_configuration(tmp_path: Path, prepared_payload: set[str]) -> None:
    """Parse only a temporary public-template fixture; never read a user's .env."""
    global TEST_HOME
    TEST_HOME = tmp_path
    directory = tmp_path / "app/docker"
    # Copy only recorded public Git blobs, never a worktree .env or stray data.
    for relative in sorted(prepared_payload):
        if relative.startswith("docker/"):
            destination = directory / relative.removeprefix("docker/")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PAYLOAD / relative, destination)
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
    # No inherited credentials, service overrides or user Docker configuration.
    environment = {
        "PATH": os.defpath,
        "HOME": str(TEST_HOME),
        "LC_ALL": "C.UTF-8",
        "COMPOSE_PROFILES": "postgresql,weaviate,collaboration",
        "DOCKER_HOST": f"unix://{TEST_HOME / 'unused-docker.sock'}",
    }
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
        env=environment,
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
        env={"PATH": os.defpath, "HOME": str(TEST_HOME), "LC_ALL": "C",
             "DIFY_INSTALL_ROOT": str(TEST_HOME / "unused-instance")},
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "ERROR:" in result.stderr


def test_bundled_runtime_and_plugin_hashes() -> None:
    expected = {
        "tools/docker-compose-linux-x86_64":
            "40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a",
        "plugins/AMDTokenFactory-0.0.10.difypkg":
            "a52e0e67f0c152d2d458ac77e4ac4fc189bd69e2d29d81f07b3f2d3555ebb528",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((PAYLOAD / relative).read_bytes()).hexdigest() == digest


def test_prepared_deployment_pin_receipt_and_canonical_sources(prepared_payload: set[str]) -> None:
    assert (PAYLOAD / ".upstream-commit").read_text().rstrip("\r\n") == DIFY_COMMIT
    assert {"LICENSE", "docker/docker-compose.yaml", "docker/.env.example"} <= prepared_payload
    for name in ("prepare_overlay.py", "amdtokenfactory_remote.py"):
        assert (PAYLOAD / "api-compat" / name).read_bytes() == (
            ROOT.parent / "api-compat" / name
        ).read_bytes()
    plugin = ROOT.parent / "plugins/amdtokenfactory"
    assert (PAYLOAD / "api-compat/model_catalog.py").read_bytes() == (
        plugin / "model_catalog.py"
    ).read_bytes()
    for name in ("INSTALL_windows_zh_Hans.txt", "README_zh_Hans.md"):
        assert (PAYLOAD / "plugins" / name).read_bytes() == (plugin / "readme" / name).read_bytes()
    assert (PAYLOAD / "plugins/PRIVACY.md").read_bytes() == (plugin / "PRIVACY.md").read_bytes()


def test_source_preparation_is_pinned_and_build_does_not_zip_the_worktree() -> None:
    preparation = (ROOT / "prepare_payload.sh").read_text()
    assert f"DIFY_COMMIT={DIFY_COMMIT}" in preparation
    assert "git --no-replace-objects" in preparation
    assert "GIT_NO_LAZY_FETCH=1" in preparation
    assert 'ls-tree -r -z --full-tree "$DIFY_COMMIT"' in preparation
    assert 'hash-object --no-filters -- "$destination"' in preparation
    assert "--offline" in preparation and "--source-repository" in preparation
    assert "curl --disable" in preparation
    assert "disappeared during offline preparation" in preparation
    assert "DIFY_SOURCE=git@github.com:langgenius/dify.git" in preparation
    assert "--network" not in preparation  # No image/container dependency at build time.
    build = (ROOT / "build.ps1").read_text()
    assert "CreateFromDirectory" not in build
    assert "CreateEntryFromFile" in build
    assert "$files[$relative] = $digest" in build
    assert "$sha.ComputeHash($stream)" in build
    assert "Payload changed while packing" in build
    assert DIFY_COMMIT in build and ".prepared.sha256" in build


@pytest.mark.parametrize("failure", ["missing_commit", "bad_package", "symlink_output"])
def test_preparation_rejects_unsafe_inputs_without_network_or_user_config(
    tmp_path: Path, failure: str,
) -> None:
    installer = tmp_path / "source/windows-installer"
    (installer / "payload/tools").mkdir(parents=True)
    script = installer / "prepare_payload.sh"
    shutil.copyfile(ROOT / "prepare_payload.sh", script)
    for relative in ("LICENSE", "tools/COMPOSE-LICENSE.txt"):
        shutil.copyfile(PAYLOAD / relative, installer / "payload" / relative)
    source_repository = tmp_path / "empty-repository"
    source_repository.mkdir()
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    git = binary_directory / "git"
    git.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$MOCK_GIT_LOG"\nexit 1\n')
    git.chmod(0o755)
    log = tmp_path / "git-log"
    package = PAYLOAD / "plugins/AMDTokenFactory-0.0.10.difypkg"
    expected = "Pinned Dify release object is missing"
    if failure == "bad_package":
        package = tmp_path / "invalid.difypkg"
        package.write_bytes(b"synthetic-invalid-package")
        expected = "does not match its pinned SHA-256"
    elif failure == "symlink_output":
        untouched = tmp_path / "untouched"
        untouched.mkdir()
        sentinel = untouched / ".env"
        sentinel.write_text("SYNTHETIC_SECRET=not-a-user-key\n")
        (installer / "payload/docker").symlink_to(untouched, target_is_directory=True)
        expected = "Unsafe generated payload directory"
    result = subprocess.run(
        ["bash", str(script), str(package), "--offline", "--source-repository",
         str(source_repository), "--compose", str(PAYLOAD / "tools/docker-compose-linux-x86_64")],
        env={"PATH": str(binary_directory) + os.pathsep + os.defpath,
             "HOME": str(tmp_path), "LC_ALL": "C", "MOCK_GIT_LOG": str(log)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2 and expected in result.stderr
    assert not (installer / "payload/.upstream-commit").exists()
    assert not any(path.is_dir() for path in installer.glob(".prepare-payload.*"))
    if failure == "missing_commit":
        arguments = log.read_text().splitlines()
        assert "cat-file" in arguments and "fetch" not in arguments and "HEAD" not in arguments
    else:
        assert not log.exists()
    if failure == "symlink_output":
        assert sentinel.read_text() == "SYNTHETIC_SECRET=not-a-user-key\n"


@pytest.mark.parametrize(
    "mode,path,expected",
    [("120000", "docker/link", "Upstream links/submodules are not allowed"),
     ("100644", "docker/../../outside", "Unsafe or private upstream path")],
)
def test_preparation_rejects_unsafe_upstream_tree_entries(
    tmp_path: Path, mode: str, path: str, expected: str,
) -> None:
    installer = tmp_path / "source/windows-installer"
    (installer / "payload/tools").mkdir(parents=True)
    script = installer / "prepare_payload.sh"
    shutil.copyfile(ROOT / "prepare_payload.sh", script)
    for relative in ("LICENSE", "tools/COMPOSE-LICENSE.txt"):
        shutil.copyfile(PAYLOAD / relative, installer / "payload" / relative)
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    git = binary_directory / "git"
    git.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        '  *"cat-file -e"*) exit 0 ;;\n'
        f'  *"rev-parse --verify"*) printf "%s\\n" "{DIFY_COMMIT}" ;;\n'
        '  *"ls-tree -r"*) printf "%s blob %s\\t%s\\0" '
        f'"{mode}" "{("1" * 40)}" "{path}" ;;\n'
        '  *) exit 1 ;;\nesac\n'
    )
    git.chmod(0o755)
    sentinel = tmp_path / "outside"
    sentinel.write_text("synthetic-untouched-file\n")
    result = subprocess.run(
        ["bash", str(script), str(PAYLOAD / "plugins/AMDTokenFactory-0.0.10.difypkg"), "--offline",
         "--source-repository", str(tmp_path), "--compose",
         str(PAYLOAD / "tools/docker-compose-linux-x86_64")],
        env={"PATH": str(binary_directory) + os.pathsep + os.defpath,
             "HOME": str(tmp_path), "LC_ALL": "C"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2 and expected in result.stderr
    assert sentinel.read_text() == "synthetic-untouched-file\n"
    assert not (installer / "payload/.upstream-commit").exists()


def test_install_script_never_removes_volumes_or_bypasses_system_security() -> None:
    script = (PAYLOAD / "windows/runtime.sh").read_text()
    for forbidden in ("down -v", "prune", "rm -rf", "sudo ", "wsl --unregister"):
        assert forbidden not in script
    assert "flock -n 9" in script
    assert "verify_existing" in script
    assert 'unix:///var/run/docker.sock' in script
    assert "-u SSRF_PROXY_ALLOW_PRIVATE_DOMAINS" in script


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
    assert not (PAYLOAD / "plugins/amdgpucloud.difypkg").exists()
    with zipfile.ZipFile(PAYLOAD / "plugins/AMDTokenFactory-0.0.10.difypkg") as archive:
        manifest = yaml.safe_load(archive.read("manifest.yaml"))
        provider = yaml.safe_load(archive.read("provider/amdtokenfactory.yaml"))
        assert manifest["version"] == "0.0.10"
        assert manifest["author"] == "amdtokenfactory"
        assert manifest["name"] == provider["provider"] == "amdtokenfactory"
        assert f'{manifest["author"]}/{manifest["name"]}/{provider["provider"]}' == (
            "amdtokenfactory/amdtokenfactory/amdtokenfactory"
        )
        assert manifest["label"] == provider["label"] == {
            "en_US": "AMDTokenFactory", "zh_Hans": "AMDTokenFactory"
        }
        assert "provider/radeon_cloud.yaml" not in archive.namelist()
        assert "provider/amdgpucloud.yaml" not in archive.namelist()
    source = (ROOT / "DifySetup.cs").read_text()
    assert "Plugin identity must be amdtokenfactory/amdtokenfactory" in source


def test_configuration_fixture_is_not_an_installed_user_directory() -> None:
    assert ".local/share" not in str(TEST_HOME)
    assert "synthetic-plugin-password" in (TEST_HOME / "app/docker/.env").read_text()


def test_dynamic_package_has_no_static_catalog_and_shares_api_parser() -> None:
    with zipfile.ZipFile(PAYLOAD / "plugins/AMDTokenFactory-0.0.10.difypkg") as archive:
        assert not any(name.startswith("models/llm/") and name.endswith(".yaml")
                       for name in archive.namelist())
        assert archive.read("model_catalog.py") == (PAYLOAD / "api-compat/model_catalog.py").read_bytes()
        provider = yaml.safe_load(archive.read("provider/amdtokenfactory.yaml"))
        assert provider["models"]["llm"]["predefined"] == []


def test_remote_catalog_overlay_is_read_only_and_keeps_database_services_untouched() -> None:
    overlay = yaml.safe_load((PAYLOAD / "windows/remote-models.override.yaml").read_text())
    assert set(overlay["services"]) == {"api", "api_websocket", "worker", "worker_beat"}
    for service in overlay["services"].values():
        assert len(service["volumes"]) == 4
        assert all(volume["read_only"] is True for volume in service["volumes"])
        assert all("docker.sock" not in volume["target"] for volume in service["volumes"])
    preparation = (PAYLOAD / "windows/prepare-remote-models.sh").read_text()
    assert "--network none" in preparation
    assert "--cap-drop ALL" in preparation
    assert "--security-opt no-new-privileges" in preparation
    assert "--user" in preparation
    generator = (PAYLOAD / "api-compat/prepare_overlay.py").read_text()
    assert "refusing to overwrite unknown implementation" in generator