"""Offline checks only: never use configured Dify model credentials."""

import base64
import struct
import subprocess
import sys
from pathlib import Path

from verify_saved_key_runtime import LEGACY_PROVIDER, PROVIDER, red_png, sanitized_answer


def test_saved_key_verifier_requires_explicit_live_permission() -> None:
    script = Path(__file__).with_name("verify_saved_key_runtime.py")
    result = subprocess.run(
        [sys.executable, str(script), "--tenant-id", "00000000-0000-0000-0000-000000000001"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "Explicit --allow-live-calls is required" in result.stderr


def test_generated_image_is_bounded_synthetic_png() -> None:
    image = base64.b64decode(red_png())
    assert image[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", image[16:24]) == (128, 128)
    assert len(image) < 1024


def test_verifier_masks_credentials_and_drops_reasoning() -> None:
    text = "<think>private reasoning</think>OK rc-syntheticfixture"
    result = sanitized_answer(text)
    assert result == "OK [REDACTED]"
    assert sanitized_answer(None) == ""
    assert len(sanitized_answer("x" * 1000)) == 200


def test_provider_choices_do_not_migrate_old_credentials() -> None:
    assert PROVIDER == "letian-kang/amdgpucloud/amdgpucloud"
    assert LEGACY_PROVIDER == "amdgpucloud/amdgpucloud/amdgpucloud"
    assert PROVIDER != LEGACY_PROVIDER