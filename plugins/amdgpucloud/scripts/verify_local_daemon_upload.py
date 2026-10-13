"""Validate a package using this local Dify deployment's native upload decoder only."""

import json
import os
import sys
from pathlib import Path
from uuid import UUID

import requests


def main() -> int:
    package = Path(sys.argv[1])
    tenant = str(UUID(os.environ["DIFY_UPLOAD_TEST_TENANT"]))
    key = os.environ.get("PLUGIN_DAEMON_KEY")
    endpoint = os.environ.get("PLUGIN_DAEMON_URL", "")
    if not key or endpoint.rstrip("/") != "http://plugin_daemon:5002":
        print("Local Dify service configuration is unavailable; no request sent")
        return 2
    url = f"http://plugin_daemon:5002/plugin/{tenant}/management/install/upload/package"
    try:
        with requests.Session() as session, package.open("rb") as stream:
            session.trust_env = False
            response = session.post(
                url,
                headers={"X-Api-Key": key},
                files={"dify_pkg": (package.name, stream, "application/octet-stream")},
                data={"verify_signature": "false"},
                timeout=(5, 60),
                allow_redirects=False,
            )
            payload = response.json()
    except (OSError, ValueError, requests.RequestException):
        print("Native local package upload failed; sensitive diagnostics suppressed")
        return 2
    data = payload.get("data") or {}
    manifest = data.get("manifest") or {}
    message = str(payload.get("message", ""))
    descriptions = manifest.get("description") or {}
    attribution_valid = all(
        isinstance(descriptions.get(locale), str)
        and "Letian Kang" in descriptions[locale]
        and "Letian.Kang@amd.com" in descriptions[locale]
        for locale in ("en_US", "zh_Hans")
    )
    identity_valid = (
        manifest.get("author") == "letian-kang"
        and manifest.get("name") == "amdgpucloud"
        and manifest.get("version") == "0.0.8"
        and str(data.get("unique_identifier", "")).startswith("letian-kang/amdgpucloud:0.0.8@")
    )
    print(json.dumps({
        "http_status": response.status_code,
        "daemon_code": payload.get("code"),
        "unique_identifier": data.get("unique_identifier"),
        "author": manifest.get("author"),
        "name": manifest.get("name"),
        "version": manifest.get("version"),
        "invalid_identifier": "plugin_unique_identifier is not valid" in message,
        "signature_error": "signature" in message.lower(),
        "decoded_author_contact_in_both_locales": attribution_valid,
        "decoded_amdgpucloud_identity": identity_valid,
        "installed_into_workspace": False,
    }))
    valid = (
        response.status_code == 200 and payload.get("code") == 0
        and attribution_valid and identity_valid
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())