import json
from unittest.mock import ANY, patch

import pytest
import requests
from dify_plugin.errors.model import CredentialsValidateFailedError

from models._credentials import (
    CHAT_COMPLETIONS_URL,
    MODELS_URL,
    validate_api_key,
    validate_model_access,
)
from provider.amdtokenfactory import AMDTokenFactoryModelProvider

VALIDATION_MODEL = "Qwen3.8-27B"


def response(status: int, payload: object) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = (
        payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    )
    result._content_consumed = True
    result.headers["Content-Type"] = "application/json"
    return result


@patch("models._transport.requests.post")
def test_provider_validation_uses_minimal_completion(post) -> None:
    post.return_value = response(
        200,
        {"choices": [{"message": {"content": "OK"}}], "usage": {}},
    )
    provider = AMDTokenFactoryModelProvider.__new__(AMDTokenFactoryModelProvider)

    provider.validate_provider_credentials({"api_key": "  rc-test  "})

    post.assert_called_once_with(
        CHAT_COMPLETIONS_URL,
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer rc-test",
            "X-Source": "dify",
            "Content-Type": "application/json",
        },
        json={
            "model": VALIDATION_MODEL,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "max_tokens": 1,
            "stream": False,
        },
        timeout=(10, 30),
        allow_redirects=False,
        stream=True,
        auth=ANY,
    )


@patch("models._transport.requests.get")
@patch("models._transport.requests.post")
def test_model_validation_requires_exact_model_access(post, get) -> None:
    post.return_value = response(200, {"choices": [{"message": {"content": "OK"}}]})
    get.return_value = response(
        200,
        {"object": "list", "data": [{"id": "DeepSeek-V4-Flash"}]},
    )

    validate_model_access({"api_key": "rc-test"}, "DeepSeek-V4-Flash")

    with pytest.raises(CredentialsValidateFailedError, match="not available"):
        validate_model_access({"api_key": "rc-test"}, "deepseek-v4-flash")
    assert post.call_count == get.call_count == 2
    assert {call.args[0] for call in post.call_args_list} == {CHAT_COMPLETIONS_URL}
    assert {call.args[0] for call in get.call_args_list} == {MODELS_URL}


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "Invalid AMD Token Factory API key"),
        (503, "temporarily unavailable"),
    ],
)
@patch("models._transport.requests.post")
def test_status_errors_are_sanitized(post, status: int, message: str) -> None:
    post.return_value = response(status, {"error": {"message": "sensitive"}})

    with pytest.raises(CredentialsValidateFailedError, match=message) as error:
        validate_api_key({"api_key": "rc-secret"})

    assert "sensitive" not in str(error.value)
    assert "rc-secret" not in str(error.value)


@patch("models._transport.requests.post")
def test_timeout_is_not_reported_as_invalid_key(post) -> None:
    post.side_effect = requests.Timeout("secret endpoint detail")

    with pytest.raises(CredentialsValidateFailedError, match="timed out") as error:
        validate_api_key({"api_key": "rc-secret"})

    assert "secret endpoint detail" not in str(error.value)


def test_missing_key_is_rejected_without_network() -> None:
    with patch("models._transport.requests.post") as post:
        with pytest.raises(CredentialsValidateFailedError, match="API key is required"):
            validate_api_key({"api_key": "  "})
        post.assert_not_called()
