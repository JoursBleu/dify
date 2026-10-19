"""Exercise the real Requests/SDK boundary without sending any external requests."""

import io
import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import pytest
import requests
import yaml
from dify_plugin.entities.model import AIModelEntity
from dify_plugin.entities.model.llm import LLMResult
from dify_plugin.entities.model.message import (
    ImagePromptMessageContent,
    PromptMessageTool,
    TextPromptMessageContent,
    ToolPromptMessage,
    UserPromptMessage,
)
from dify_plugin.errors.model import (
    InvokeAuthorizationError,
    InvokeBadRequestError,
    InvokeConnectionError,
    InvokeError,
    InvokeRateLimitError,
    InvokeServerUnavailableError,
)

from models._credentials import CHAT_COMPLETIONS_URL
from models.llm.llm import AMDTokenFactoryLargeLanguageModel

ROOT = Path(__file__).resolve().parents[1]
MODEL = "DeepSeek-V4-Flash"
KEY = "rc-offline-fixture"
SENSITIVE_BODY = "synthetic private upstream error: rc-offline-fixture"
USAGE = {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}


class WireBody(io.BytesIO):
    def __init__(self, content: bytes, split: int = 7) -> None:
        super().__init__(content)
        self.split = split

    def stream(self, chunk_size: int, decode_content: bool = True):
        del chunk_size, decode_content
        while part := self.read(self.split):
            yield part

    def release_conn(self) -> None:
        # urllib3 releases fully consumed bodies through this method, not raw.close().
        self.close()


def wire_response(status: int, content: bytes) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.encoding = "utf-8"
    response.headers["Content-Type"] = "application/json"
    response.raw = WireBody(content)
    return response


def completion(message: dict | None = None) -> dict:
    return {
        "id": "chatcmpl-offline",
        "model": MODEL,
        "object": "chat.completion",
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": message or {"content": "OK"}}
        ],
        "usage": USAGE,
    }


def sse(*deltas: dict, done: bool = True) -> bytes:
    events = [": keepalive"]
    for delta in deltas:
        events.append(
            "data: "
            + json.dumps(
                {
                    "id": "chatcmpl-offline",
                    "model": MODEL,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                },
                ensure_ascii=False,
            )
        )
    events.append(
        "data: "
        + json.dumps(
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": USAGE}
        )
    )
    if done:
        events.append("data: [DONE]")
    return ("\n".join(event + "\n" for event in events) + "\n").encode()


@pytest.fixture
def model() -> AMDTokenFactoryLargeLanguageModel:
    schemas = [AIModelEntity.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
               for path in (ROOT / "models/llm").glob("catalog-*.yaml")]
    return AMDTokenFactoryLargeLanguageModel(model_schemas=schemas)


@pytest.fixture
def wire(monkeypatch) -> tuple[list, Callable]:
    calls = []
    replies: list[requests.Response | Exception] = []

    def send(session, request, **kwargs):
        del session
        assert request.method == "POST" and request.url == CHAT_COMPLETIONS_URL
        calls.append((request, kwargs))
        assert replies, "An unexpected extra HTTP request was attempted"
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        reply.request = request
        return reply

    monkeypatch.setattr(requests.sessions.Session, "send", send)

    def enqueue(content: bytes | dict, status: int = 200) -> requests.Response:
        raw = content if isinstance(content, bytes) else json.dumps(content).encode()
        response = wire_response(status, raw)
        replies.append(response)
        return response

    return calls, enqueue


def invoke(model, *, stream: bool = False, name: str = MODEL, **kwargs):
    return model._invoke(
        model=name,
        credentials=kwargs.pop("credentials", {"api_key": KEY}),
        prompt_messages=kwargs.pop("messages", [UserPromptMessage(content="中文 hi")]),
        model_parameters=kwargs.pop("parameters", {"max_tokens": 16}),
        stream=stream,
        **kwargs,
    )


def test_real_request_is_fixed_non_mutating_and_closes_response(model, wire) -> None:
    calls, enqueue = wire
    response = enqueue(completion())
    credentials = {
        "api_key": f"  {KEY}  ",
        "endpoint_url": "https://not-used.invalid/v1",
        "extra_headers": {"x-source": "spoof", "X-Custom": "preserved"},
    }
    parameters = {"max_tokens": 16, "response_format": "text"}
    original = deepcopy((credentials, parameters))

    result = invoke(
        model, credentials=credentials, parameters=parameters, stop=["END"], user="test"
    )

    assert isinstance(result, LLMResult)
    assert result.message.content == "OK"
    assert result.usage.total_tokens == 14
    assert len(calls) == 1
    request, options = calls[0]
    assert request.url == CHAT_COMPLETIONS_URL
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.headers["X-Source"] == "dify"
    assert request.headers["X-Custom"] == "preserved"
    assert options["allow_redirects"] is False
    assert options["timeout"] == (10, 300)
    payload = json.loads(request.body)
    assert payload["model"] == MODEL
    assert payload["messages"] == [{"role": "user", "content": "中文 hi"}]
    assert payload["response_format"] == {"type": "text"}
    assert payload["stop"] == ["END"]
    assert payload["user"] == "test"
    assert (credentials, parameters) == original
    assert response.raw.closed


def test_non_stream_reasoning_and_tool_history_use_actual_wire(model, wire) -> None:
    calls, enqueue = wire
    tool_call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "marker", "arguments": "{}"},
    }
    enqueue(completion({
        "role": "assistant",
        "content": None,
        "reasoning_content": "想一想 </think>",
        "tool_calls": [tool_call],
    }))
    tool = PromptMessageTool(
        name="marker", description="Return a marker", parameters={"type": "object"}
    )
    result = invoke(model, tools=[tool])
    assert result.message.opaque_body["reasoning_content"] == "想一想 </think>"
    assert result.message.tool_calls[0].id == "call-1"
    saved = result.message.model_dump()

    enqueue(completion())
    invoke(
        model,
        messages=[
            result.message,
            ToolPromptMessage(content="marker-result", tool_call_id="call-1"),
        ],
        tools=[tool],
    )

    payload = json.loads(calls[-1][0].body)
    assert payload["tool_choice"] == "auto"
    assert payload["tools"][0]["function"]["name"] == "marker"
    assert payload["messages"][0]["content"] == ""
    assert payload["messages"][0]["reasoning_content"] == "想一想 </think>"
    assert payload["messages"][0]["tool_calls"][0] == tool_call
    assert payload["messages"][1] == {
        "role": "tool", "tool_call_id": "call-1", "content": "marker-result"
    }
    assert result.message.model_dump() == saved


def test_stream_handles_unicode_reasoning_tool_fragments_and_usage(model, wire) -> None:
    calls, enqueue = wire
    response = enqueue(sse(
        {"reasoning_content": "思考 </think> &"},
        {"reasoning_content": ""},
        {"tool_calls": [{
            "index": 0,
            "id": "call-1",
            "type": "function",
            "function": {"name": "marker", "arguments": '{"city":'},
        }]},
        {"tool_calls": [{"index": 0, "function": {"arguments": '"无锡"}'}}]},
    ))
    chunks = list(invoke(model, stream=True))
    text = "".join(chunk.delta.message.content or "" for chunk in chunks)
    answer, reasoning = model._extract_reasoning_content(text)
    assert answer == ""
    assert reasoning == "思考 </think> &"
    tools = [call for chunk in chunks for call in chunk.delta.message.tool_calls]
    assert len(tools) == 1
    assert tools[0].id == "call-1"
    assert json.loads(tools[0].function.arguments) == {"city": "无锡"}
    assert chunks[-1].delta.usage.total_tokens == 14
    assert chunks[-1].delta.finish_reason == "stop"
    assert calls[0][1]["allow_redirects"] is False
    assert json.loads(calls[0][0].body)["stream_options"] == {"include_usage": True}
    assert response.raw.closed


def test_stream_eof_without_done_is_an_error(model, wire) -> None:
    _, enqueue = wire
    response = enqueue(sse({"content": "partial"}, done=False))
    with pytest.raises(InvokeError, match="incomplete"):
        list(invoke(model, stream=True))
    assert response.raw.closed


@pytest.mark.parametrize("status,kind", [
    (401, InvokeAuthorizationError),
    (429, InvokeRateLimitError),
    (503, InvokeServerUnavailableError),
    (302, InvokeConnectionError),
])
def test_generation_status_errors_are_typed_and_sanitized(
    model, wire, status, kind, caplog
) -> None:
    _, enqueue = wire
    response = enqueue({"error": {"message": SENSITIVE_BODY}}, status=status)
    with pytest.raises(kind) as error:
        invoke(model)
    assert KEY not in str(error.value)
    assert SENSITIVE_BODY not in str(error.value)
    assert KEY not in caplog.text
    assert response.raw.closed


def test_base64_image_reaches_actual_http_body(model, wire) -> None:
    image = "data:image/png;base64,aW1hZ2U="
    calls, enqueue = wire
    enqueue(completion())
    image_message = ImagePromptMessageContent(format="png", mime_type="image/png", url=image)
    invoke(
        model,
        name="Qwen3.8-Flash-Next",
        messages=[UserPromptMessage(content=[
            TextPromptMessageContent(data="color?"), image_message
        ])],
    )
    content = json.loads(calls[0][0].body)["messages"][0]["content"]
    assert content == [
        {"type": "text", "text": "color?"},
        {"type": "image_url", "image_url": {"url": image, "detail": "low"}},
    ]


def test_transport_refuses_non_fixed_urls() -> None:
    from models._transport import request_response
    with pytest.raises(InvokeBadRequestError, match="fixed API endpoint"):
        request_response(
            "https://attacker.example/v1/chat/completions",
            headers={}, timeout=(1, 1), operation="test",
        )


def test_structured_output_reaches_the_wire(model, wire) -> None:
    calls, enqueue = wire
    enqueue(completion({"content": '{"ok": true}'}))
    enqueue(completion({"content": '{"ok": true}'}))
    list(model.invoke(
        model=MODEL, credentials={"api_key": KEY},
        prompt_messages=[UserPromptMessage(content="hi")],
        model_parameters={"response_format": "json_object"}, stream=False,
    ))
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    list(model.invoke(
        model=MODEL, credentials={"api_key": KEY},
        prompt_messages=[UserPromptMessage(content="hi")],
        model_parameters={"response_format": "json_schema", "json_schema": json.dumps(schema)},
        stream=False,
    ))
    assert json.loads(calls[0][0].body)["response_format"] == {"type": "json_object"}
    assert json.loads(calls[1][0].body)["response_format"] == {
        "type": "json_schema", "json_schema": schema,
    }
