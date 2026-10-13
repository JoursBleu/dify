"""Operator-only verification using Dify's installed, policy-checked PluginService.

Run inside the already-authorized local API container. No browser session is
forged, no database rows are inserted, and no service/key settings are changed.
Only public plugin metadata is printed; model schema dispatch does not infer.
"""

import argparse
import contextlib
import hashlib
import io
import json
import logging
import traceback
from pathlib import Path

PACKAGE_SHA = "66f7bd9c8e15136a57228088daa647953d0a373a430d85ee11abff9c5bc5e845"
PLUGIN_ID = "letian-kang/amdgpucloud"
VERSION = "0.0.8"
MODELS = ("DeepSeek-V4-Flash", "DeepSeek-V4.1-Flash", "Qwen3.8-Flash-Next")


def labels(value) -> dict[str, str]:
    localized = value.model_dump()
    return {locale: localized[locale] for locale in ("en_US", "zh_Hans")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "inspect"))
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--package")
    parser.add_argument("--task-id")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)

    # Startup output is not the public metadata report. Do not emit configuration.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from app_factory import create_app

        _, app = create_app()

    from core.plugin.impl.model import PluginModelClient
    from core.plugin.impl.plugin import PluginInstaller
    from core.plugin.plugin_service import PluginService
    from services.system_feature_service import SystemFeatureService

    report = {"action": args.action, "tenant_id": args.tenant_id}
    with app.app_context():
        permission = SystemFeatureService.get_plugin_installation_permission()
        report["installation_policy"] = {
            "scope": permission.plugin_installation_scope.value,
            "marketplace_only": permission.restrict_to_marketplace_only,
            "changed": False,
        }
        manager = PluginInstaller()
        before = PluginService.list(args.tenant_id)
        existing = [plugin for plugin in before if plugin.plugin_id == PLUGIN_ID]
        report["plugins_before"] = len(before)

        if args.action == "install":
            if not args.package:
                raise ValueError("Package path is required")
            package = Path(args.package)
            if not package.is_file() or package.is_symlink():
                raise ValueError("Package must be a regular non-symlink file")
            content = package.read_bytes()
            if hashlib.sha256(content).hexdigest() != PACKAGE_SHA:
                raise ValueError("Package digest does not match the reviewed delivery")
            if existing and any(plugin.version != VERSION for plugin in existing):
                raise ValueError("An existing provider version requires an explicit native upgrade")
            decoded = PluginService.upload_pkg(args.tenant_id, content)
            declaration = decoded.manifest
            if (declaration.name, declaration.author, declaration.version) != (
                "amdgpucloud", "letian-kang", VERSION
            ):
                raise ValueError("Native package identity differs from reviewed delivery")
            if labels(declaration.label) != {"en_US": "AMDGPUCloud", "zh_Hans": "AMDGPUCloud"}:
                raise ValueError("Native package branding differs from reviewed delivery")
            started = PluginService.install_from_local_pkg(args.tenant_id, [decoded.unique_identifier])
            report["upload"] = {
                "unique_identifier": decoded.unique_identifier,
                "labels": labels(declaration.label),
                "verified": decoded.verification is not None,
                "source": "package",
            }
            report["installation_start"] = {
                "all_installed": started.all_installed,
                "task_id": started.task_id,
            }
            if started.task_id:
                task = manager.fetch_plugin_installation_task(args.tenant_id, started.task_id)
                report["task"] = {
                    "status": task.status.value,
                    "completed_plugins": task.completed_plugins,
                    "total_plugins": task.total_plugins,
                    "plugins": [{"plugin_id": item.plugin_id, "status": item.status.value}
                                for item in task.plugins],
                }
        else:
            if args.task_id:
                task = manager.fetch_plugin_installation_task(args.tenant_id, args.task_id)
                report["task"] = {
                    "status": task.status.value,
                    "completed_plugins": task.completed_plugins,
                    "total_plugins": task.total_plugins,
                    "plugins": [{"plugin_id": item.plugin_id, "status": item.status.value}
                                for item in task.plugins],
                }
            if len(existing) != 1:
                raise ValueError("Expected one native AMDGPUCloud installation")
            installed = existing[0]
            if installed.version != VERSION:
                raise ValueError("Installed native plugin version differs from delivery")
            report["installed_plugin"] = {
                "plugin_id": installed.plugin_id,
                "unique_identifier": installed.plugin_unique_identifier,
                "version": installed.version,
                "source": installed.source.value,
                "runtime_type": installed.runtime_type,
                "category": installed.declaration.category.value,
                "labels": labels(installed.declaration.label),
            }
            if report["installed_plugin"]["labels"] != {
                "en_US": "AMDGPUCloud", "zh_Hans": "AMDGPUCloud"
            }:
                raise ValueError("Installed plugin labels do not match AMDGPUCloud")
            # Use the same tenant-scoped discovery/cache service used by the UI.
            providers = PluginService.fetch_plugin_model_providers(tenant_id=args.tenant_id)
            branded = [provider for provider in providers
                       if provider.plugin_unique_identifier == installed.plugin_unique_identifier]
            if len(branded) != 1:
                raise ValueError("Expected one native model-provider declaration")
            provider = branded[0]
            if provider.provider != "letian-kang/amdgpucloud/amdgpucloud":
                raise ValueError("Canonical model provider contains a previous identity")
            report["model_provider"] = {
                "provider": provider.provider,
                "labels": labels(provider.label),
                "source": provider.installation_source.value,
                "key_help_url": labels(provider.help.url)["en_US"],
            }
            client = PluginModelClient()
            schemas = []
            for model in MODELS:
                schema = client.get_model_schema(
                    tenant_id=args.tenant_id,
                    user_id=None,
                    plugin_id=PLUGIN_ID,
                    provider="amdgpucloud",
                    model_type="llm",
                    model=model,
                    credentials={},
                )
                if schema is None or schema.model != model:
                    raise ValueError("Native model schema dispatch did not return its predefined model")
                schemas.append({"model": schema.model, "model_type": schema.model_type.value})
            report["runtime_model_schemas"] = schemas
            report["inference_requests"] = 0
            report["credentials_written"] = False

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Upstream exceptions can contain headers or configuration. Never print them.
        frames = traceback.extract_tb(error.__traceback__)
        local_frames = [frame for frame in frames if frame.filename == __file__]
        frame = (local_frames or frames)[-1]
        print(json.dumps({"result": "failed", "error_type": type(error).__name__,
                          "location": {"file": Path(frame.filename).name, "line": frame.lineno,
                                       "function": frame.name},
                          "detail": "Native verification failed; inspect safe scoped diagnostics."}))
        raise SystemExit(1) from None