import os
from pathlib import Path

import pytest
import yaml
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

from models.llm.llm import AMDTokenFactoryLargeLanguageModel

API_KEY = os.getenv("AMDTOKENFACTORY_API_KEY", "").strip()
LIVE_ENABLED = os.getenv("RUN_AMDTOKENFACTORY_LIVE") == "1"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (API_KEY and LIVE_ENABLED),
        reason="set RUN_AMDTOKENFACTORY_LIVE=1 and AMDTOKENFACTORY_API_KEY",
    ),
]


class _Credentials(dict[str, str]):
    def __repr__(self) -> str:
        return "AMD Token Factory live-test credentials"

    __str__ = __repr__


ROOT = Path(__file__).resolve().parents[1]
PACKAGED = [yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in sorted((ROOT / "models/llm").glob("catalog-*.yaml"))]
llm = AMDTokenFactoryLargeLanguageModel(model_schemas=[])


@pytest.fixture(scope="module")
def catalog():
    from dify_plugin.entities.model import AIModelEntity
    llm.model_schemas = [AIModelEntity.model_validate(schema) for schema in PACKAGED]
    return PACKAGED


def _invoke(
    messages: list[PromptMessage],
    *,
    model: str,
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
            user="amdtokenfactory-dify-live-test",
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


def test_packaged_models_accept_a_minimal_request(catalog) -> None:
    assert catalog
    for schema in catalog:
        chunks = _invoke(
            [UserPromptMessage(content="Reply only with OK.")],
            model=schema["model"], parameters={"max_tokens": 32}, stream=False,
        )
        assert _text(chunks).strip()
        _terminal(chunks)


def test_streaming_reasoning_closes_cleanly(catalog) -> None:
    chunks = _invoke(
        [UserPromptMessage(content="Calculate 17 * 19, then reply with 323.")],
        model=next(s["model"] for s in catalog if "agent-thought" in s["features"]),
        parameters={"max_tokens": 256},
        stream=True,
    )

    text = _text(chunks)
    assert "323" in text
    assert "<think>" in text
    assert text.count("<think>") == text.count("</think>")
    _terminal(chunks)


def test_packaged_vision_model_reads_inline_image(catalog) -> None:
    candidates = [schema for schema in catalog if "vision" in schema["features"]]
    model = candidates[0]["model"]
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


def test_tool_call_and_result_round_trip(catalog) -> None:
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
        model=next(s["model"] for s in catalog if "tool-call" in s["features"]),
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
                    content='{"marker":"DIFY_AMDTF_OK"}',
                    tool_call_id=call.id,
                )
                for call in assistant.tool_calls
            ],
        ],
        model=next(s["model"] for s in catalog if "tool-call" in s["features"]),
        parameters={"max_tokens": 256},
        tools=[tool],
        stream=False,
    )

    assert "DIFY_AMDTF_OK" in _text(second)
    _terminal(second)