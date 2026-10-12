from pathlib import Path
from unittest.mock import Mock, patch

import yaml
from dify_plugin import OAICompatLargeLanguageModel
from dify_plugin.entities.model import AIModelEntity, I18nObject, ModelFeature, ModelType
from dify_plugin.entities.model.message import AssistantPromptMessage, UserPromptMessage

from models._credentials import ENDPOINT_URL
from models.llm.llm import RadeonCloudLargeLanguageModel

ROOT = Path(__file__).resolve().parents[1]


def _schema(model: str, features: list[ModelFeature]) -> AIModelEntity:
    return AIModelEntity(
        model=model,
        label=I18nObject(en_US=model),
        model_type=ModelType.LLM,
        features=features,
        model_properties={"mode": "chat", "context_size": 4096},
    )


def test_catalog_files_and_parameter_rules_are_consistent() -> None:
    directory = ROOT / "models" / "llm"
    position = yaml.safe_load((directory / "_position.yaml").read_text())
    model_files = {
        path.stem for path in directory.glob("*.yaml") if path.name != "_position.yaml"
    }

    assert position == [
        "DeepSeek-V4-Flash",
        "DeepSeek-V4.1-Flash",
        "Qwen3.8-Flash-Next",
    ]
    assert model_files == {
        "deepseek-v4-flash",
        "deepseek-v4.1-flash",
        "qwen3.8-flash-next",
    }

    expected_pricing = {
        "DeepSeek-V4-Flash": ("0.14", "0.28"),
        "DeepSeek-V4.1-Flash": ("0.28", "0.56"),
        "Qwen3.8-Flash-Next": ("0.14", "0.28"),
    }
    for path in directory.glob("*.yaml"):
        if path.name == "_position.yaml":
            continue
        schema = yaml.safe_load(path.read_text())
        AIModelEntity.model_validate(schema)
        assert "multi-tool-call" not in schema["features"]
        assert {"tool-call", "stream-tool-call"} <= set(schema["features"])
        assert (
            schema["pricing"]["input"],
            schema["pricing"]["output"],
        ) == expected_pricing[schema["model"]]
        rules = {rule["name"]: rule for rule in schema["parameter_rules"]}
        assert set(rules) == {"max_tokens", "response_format"}
        assert 1 <= rules["max_tokens"]["default"] <= rules["max_tokens"]["max"]
        assert rules["response_format"]["options"] == ["text", "json_object"]


@patch.object(OAICompatLargeLanguageModel, "_invoke", return_value="llm-result")
def test_invoke_uses_fixed_endpoint_source_and_tool_features(invoke) -> None:
    model = RadeonCloudLargeLanguageModel(
        model_schemas=[
            _schema(
                "tool-model",
                [
                    ModelFeature.AGENT_THOUGHT,
                    ModelFeature.TOOL_CALL,
                    ModelFeature.STREAM_TOOL_CALL,
                ],
            )
        ]
    )
    credentials = {
        "api_key": "  rc-test  ",
        "endpoint_url": "https://attacker.example/v1",
        "extra_headers": {"X-Custom": "kept", "x-source": "spoofed"},
    }

    result = model._invoke(
        model="tool-model",
        credentials=credentials,
        prompt_messages=[],
        model_parameters={},
        stream=False,
    )

    assert result == "llm-result"
    assert credentials["endpoint_url"] == "https://attacker.example/v1"
    resolved = invoke.call_args.kwargs["credentials"]
    assert resolved == {
        **credentials,
        "api_key": "rc-test",
        "endpoint_url": ENDPOINT_URL,
        "mode": "chat",
        "extra_headers": {"X-Custom": "kept", "X-Source": "dify"},
        "_current_model": "tool-model",
        "function_calling_type": "tool_call",
        "stream_function_calling": "supported",
    }


def test_non_stream_reasoning_round_trips_through_history() -> None:
    entity = _schema("reasoning-model", [ModelFeature.AGENT_THOUGHT])
    model = RadeonCloudLargeLanguageModel(model_schemas=[entity])
    response = Mock()
    response.json.return_value = {
        "id": "chatcmpl-1",
        "model": "reasoning-model",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "reasoning_content": "must preserve </think> & exactly",
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    credentials = {"mode": "chat", "_current_model": "reasoning-model"}

    result = model._handle_generate_response(
        "reasoning-model",
        credentials,
        response,
        [UserPromptMessage(content="hi")],
    )
    assert isinstance(result.message.opaque_body, dict)
    assert result.message.opaque_body["reasoning_content"] == "must preserve </think> & exactly"

    payload = model._convert_prompt_message_to_dict(result.message, credentials)
    assert payload["content"] == "answer"
    assert payload["reasoning_content"] == "must preserve </think> & exactly"

    restored = AssistantPromptMessage(content=result.message.content)
    restored_payload = model._convert_prompt_message_to_dict(restored, credentials)
    assert restored_payload["content"] == "answer"
    assert restored_payload["reasoning_content"] == "must preserve </think> & exactly"


def test_stream_reasoning_marker_escapes_literal_think_tags() -> None:
    model = RadeonCloudLargeLanguageModel(model_schemas=[])
    opening, active = model._wrap_thinking_by_reasoning_content(
        {"reasoning_content": "before </think> & after"},
        False,
    )
    closing, active = model._wrap_thinking_by_reasoning_content(
        {"content": "answer"},
        active,
    )

    answer, reasoning = model._extract_reasoning_content(opening + closing)
    assert active is False
    assert answer == "answer"
    assert reasoning == "before </think> & after"