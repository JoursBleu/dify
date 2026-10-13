import json
import os
from pathlib import Path

import pytest
import yaml
from dify_plugin.entities.model import AIModelEntity
from dify_plugin.entities.model.llm import LLMResultChunk
from dify_plugin.entities.model.message import (
    AssistantPromptMessage,
    ImagePromptMessageContent,
    PromptMessage,
    PromptMessageTool,
    TextPromptMessageContent,
    ToolPromptMessage,
    UserPromptMessage,
)

from models.llm.llm import AMDGPUCloudLargeLanguageModel

ROOT = Path(__file__).resolve().parents[1]
MODELS = tuple(yaml.safe_load((ROOT / "models" / "llm" / "_position.yaml").read_text()))
API_KEY = os.getenv("RADEON_API_KEY", "").strip()
LIVE_ENABLED = os.getenv("RUN_RADEON_LIVE") == "1"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (API_KEY and LIVE_ENABLED),
        reason="set RUN_RADEON_LIVE=1 and RADEON_API_KEY",
    ),
]


class _Credentials(dict[str, str]):
    def __repr__(self) -> str:
        return "AMDGPUCloud live-test credentials"

    __str__ = __repr__


schemas = [
    AIModelEntity.model_validate(
        yaml.safe_load((ROOT / "models" / "llm" / f"{model.lower()}.yaml").read_text())
    )
    for model in MODELS
]
llm = AMDGPUCloudLargeLanguageModel(model_schemas=schemas)


def _invoke(
    messages: list[PromptMessage],
    *,
    model: str = "DeepSeek-V4-Flash",
    parameters: dict,
    tools: list[PromptMessageTool] | None = None,
    stream: bool,
) -> list[LLMResultChunk]:
    return list(
        llm.invoke(
            model=model,
            credentials=_Credentials(api_key=API_KEY),
            prompt_messages=messages,
            model_parameters=parameters,
            tools=tools,
            stream=stream,
            user="amdgpucloud-dify-live-test",
        )
    )


def _text(chunks: list[LLMResultChunk]) -> str:
    return "".join(
        chunk.delta.message.content
        for chunk in chunks
        if isinstance(chunk.delta.message.content, str)
    )


def _terminal(chunks: list[LLMResultChunk]):
    assert chunks
    terminal = chunks[-1].delta
    assert terminal.usage is not None
    assert terminal.usage.total_tokens > 0
    return terminal


@pytest.mark.parametrize("model", MODELS)
def test_every_initial_model_accepts_a_minimal_request(model: str) -> None:
    chunks = _invoke(
        [UserPromptMessage(content="Reply only with OK.")],
        model=model,
        parameters={"max_tokens": 32},
        stream=False,
    )

    assert _text(chunks).strip()
    _terminal(chunks)


def test_streaming_reasoning_closes_cleanly() -> None:
    chunks = _invoke(
        [UserPromptMessage(content="Calculate 17 * 19, then reply with 323.")],
        parameters={"max_tokens": 256},
        stream=True,
    )

    text = _text(chunks)
    assert "323" in text
    assert text.count("<think>") == text.count("</think>")
    _terminal(chunks)


@pytest.mark.parametrize("model", ["DeepSeek-V4.1-Flash", "Qwen3.8-Flash-Next"])
def test_vision_models_read_inline_image(model: str) -> None:
    image = ImagePromptMessageContent(
        format="png",
        mime_type="image/png",
        base64_data=(
            "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKElEQVR4nO3NsQ0A"
            "AAzCMP5/un0CNkuZ41wybXsHAAAAAAAAAAAAxR4yw/wuPL6QkAAAAABJRU5ErkJggg=="
        ),
    )
    chunks = _invoke(
        [
            UserPromptMessage(
                content=[
                    TextPromptMessageContent(
                        data="Name the color of this image in one English word."
                    ),
                    image,
                ]
            )
        ],
        model=model,
        parameters={"max_tokens": 32},
        stream=False,
    )

    assert "red" in _text(chunks).lower()
    _terminal(chunks)


def test_json_object_output() -> None:
    chunks = _invoke(
        [UserPromptMessage(content='Return only this JSON object: {"answer":"OK"}')],
        parameters={"max_tokens": 64, "response_format": "json_object"},
        stream=False,
    )

    assert json.loads(_text(chunks))["answer"] == "OK"
    _terminal(chunks)


def test_tool_call_and_result_round_trip() -> None:
    tool = PromptMessageTool(
        name="get_live_marker",
        description="Return the marker required to answer the user.",
        parameters={"type": "object", "properties": {}},
    )
    prompt = UserPromptMessage(
        content="Call get_live_marker exactly once, then answer with its result."
    )
    first = _invoke(
        [prompt],
        parameters={"max_tokens": 256},
        tools=[tool],
        stream=False,
    )
    assistant = _terminal(first).message
    assert isinstance(assistant, AssistantPromptMessage)
    assert assistant.tool_calls

    second = _invoke(
        [
            prompt,
            assistant,
            *[
                ToolPromptMessage(
                    content='{"marker":"DIFY_RADEON_OK"}',
                    tool_call_id=call.id,
                )
                for call in assistant.tool_calls
            ],
        ],
        parameters={"max_tokens": 256},
        tools=[tool],
        stream=False,
    )

    assert "DIFY_RADEON_OK" in _text(second)
    _terminal(second)