"""Bounded native Dify calls using credentials already saved by the user.

Run inside the API container with explicit --allow-live-calls. This script
never accepts a key, writes an app, changes a provider or migrates credentials.
Use --provider for the older installed 0.0.7 identity when checking that instance.
Only synthetic prompts and a generated solid-color PNG are transmitted.
"""

import argparse
import base64
import contextlib
import io
import json
import logging
import re
import signal
import struct
import time
import traceback
import zlib
from datetime import UTC, datetime
from uuid import UUID

PROVIDER = "letian-kang/amdgpucloud/amdgpucloud"
LEGACY_PROVIDER = "amdgpucloud/amdgpucloud/amdgpucloud"
CASES = {
    "text": ("DeepSeek-V4-Flash", "OK", False),
    "vision-deepseek": ("DeepSeek-V4.1-Flash", "red", True),
    "vision-qwen": ("Qwen3.8-Flash-Next", "red", True),
}


class DiscardOutput(io.TextIOBase):
    def write(self, text: str) -> int:
        return len(text)


def red_png() -> str:
    def chunk(kind: bytes, content: bytes) -> bytes:
        return (struct.pack(">I", len(content)) + kind + content
                + struct.pack(">I", zlib.crc32(kind + content)))

    size = 128
    scanlines = (b"\0" + b"\xff\0\0" * size) * size
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode("ascii")


def sanitized_answer(content: object) -> str:
    if not isinstance(content, str):
        return ""
    answer = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
    answer = re.sub(r"\b(?:rc-|rcsk_|sk-)[A-Za-z0-9_-]{8,}\b", "[REDACTED]", answer)
    return answer.strip()[:200]


def timeout_handler(_signum, _frame) -> None:
    raise TimeoutError("Bounded live verification timed out")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--provider", choices=(PROVIDER, LEGACY_PROVIDER), default=PROVIDER)
    parser.add_argument("--case", choices=(*CASES, "all"), default="all")
    parser.add_argument("--allow-live-calls", action="store_true")
    args = parser.parse_args()
    if not args.allow_live_calls:
        parser.error("Explicit --allow-live-calls is required")
    logging.disable(logging.CRITICAL)

    with contextlib.redirect_stdout(DiscardOutput()), contextlib.redirect_stderr(DiscardOutput()):
        from app_factory import create_app

        _, app = create_app()
        from core.model_manager import ModelManager
        from graphon.model_runtime.entities.message_entities import (
            ImagePromptMessageContent,
            TextPromptMessageContent,
            UserPromptMessage,
        )
        from graphon.model_runtime.entities.model_entities import ModelFeature, ModelType

    report = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "provider": args.provider,
        "credential_source": "Dify native saved credential resolver",
        "credentials_printed": False,
        "provider_settings_changed": False,
        "max_output_tokens_per_call": 128,
        "automatic_retries": 0,
        "tests": [],
    }
    cases = CASES if args.case == "all" else {args.case: CASES[args.case]}
    signal.signal(signal.SIGALRM, timeout_handler)
    with app.app_context():
        tenant = str(args.tenant_id)
        manager = ModelManager.for_tenant(tenant)
        for name, (model, expected, image) in cases.items():
            started = time.monotonic()
            row = {"case": name, "model": model, "synthetic_image": image}
            try:
                with (contextlib.redirect_stdout(DiscardOutput()),
                      contextlib.redirect_stderr(DiscardOutput())):
                    signal.alarm(180)
                    instance = manager.get_model_instance(
                        tenant_id=tenant, provider=args.provider,
                        model_type=ModelType.LLM, model=model,
                    )
                    schema = instance.get_model_schema()
                    vision = ModelFeature.VISION in (schema.features or [])
                    if image and not vision:
                        raise ValueError("Image test requires the native vision feature")
                    if image:
                        message = UserPromptMessage(content=[
                            TextPromptMessageContent(data=(
                                "Name the dominant color of the image in one English word. "
                                "Do not explain."
                            )),
                            ImagePromptMessageContent(
                                format="png", mime_type="image/png", base64_data=red_png(),
                            ),
                        ])
                    else:
                        message = UserPromptMessage(content="Reply with exactly OK. Do not explain.")
                    result = instance.invoke_llm(
                        prompt_messages=[message], model_parameters={"max_tokens": 128},
                        stream=False,
                    )
                    answer = sanitized_answer(result.message.content)
                    row.update({
                        "vision_declared": vision,
                        "answer": answer,
                        "expected": expected,
                        "passed": expected.lower() in answer.lower().split(),
                        "usage": {
                            "prompt_tokens": result.usage.prompt_tokens,
                            "completion_tokens": result.usage.completion_tokens,
                            "total_tokens": result.usage.total_tokens,
                        },
                    })
            except Exception as error:
                local = [frame for frame in traceback.extract_tb(error.__traceback__)
                         if frame.name == "main"]
                row.update({"passed": False, "error_type": type(error).__name__,
                            "local_line": local[-1].lineno if local else None})
            finally:
                signal.alarm(0)
                row["elapsed_seconds"] = round(time.monotonic() - started, 3)
            report["tests"].append(row)
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    report["all_passed"] = all(row["passed"] for row in report["tests"])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"result": "failed", "error_type": type(error).__name__,
                          "detail": "Sensitive diagnostics suppressed"}))
        raise SystemExit(1) from None