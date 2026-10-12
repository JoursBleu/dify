from collections.abc import Mapping
from http import HTTPStatus

import requests
from dify_plugin.errors.model import CredentialsValidateFailedError

ENDPOINT_URL = "https://developer.amd.com.cn/radeon/api/v1"
MODELS_URL = f"{ENDPOINT_URL}/models"
CHAT_COMPLETIONS_URL = f"{ENDPOINT_URL}/chat/completions"
SOURCE_HEADER = "X-Source"
SOURCE_VALUE = "dify"
VALIDATION_MODEL = "DeepSeek-V4-Flash"
VALIDATION_TIMEOUT = (10, 30)
MAX_MODELS_RESPONSE_BYTES = 2 * 1024 * 1024


def normalize_api_key(credentials: Mapping) -> str:
    api_key = credentials.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise CredentialsValidateFailedError("Radeon Cloud API key is required")
    return api_key.strip()


def validation_headers(credentials: Mapping) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {normalize_api_key(credentials)}",
        SOURCE_HEADER: SOURCE_VALUE,
    }


def validate_api_key(credentials: Mapping) -> None:
    headers = {
        **validation_headers(credentials),
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            CHAT_COMPLETIONS_URL,
            headers=headers,
            json={
                "model": VALIDATION_MODEL,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 1,
                "stream": False,
            },
            timeout=VALIDATION_TIMEOUT,
            allow_redirects=False,
        )
    except requests.Timeout as ex:
        raise CredentialsValidateFailedError(
            "Radeon Cloud credential validation timed out"
        ) from ex
    except requests.RequestException as ex:
        raise CredentialsValidateFailedError(
            "Unable to reach Radeon Cloud for credential validation"
        ) from ex

    if response.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        raise CredentialsValidateFailedError("Invalid Radeon Cloud API key")
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise CredentialsValidateFailedError(
            "Radeon Cloud credential validation was rate limited"
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise CredentialsValidateFailedError(
            "Radeon Cloud is temporarily unavailable for credential validation"
        )
    if response.status_code != HTTPStatus.OK:
        raise CredentialsValidateFailedError(
            f"Radeon Cloud credential validation failed with status {response.status_code}"
        )


def validate_model_access(credentials: Mapping, model: str) -> None:
    validate_api_key(credentials)
    try:
        response = requests.get(
            MODELS_URL,
            headers=validation_headers(credentials),
            timeout=VALIDATION_TIMEOUT,
            allow_redirects=False,
        )
    except requests.Timeout as ex:
        raise CredentialsValidateFailedError(
            "Radeon Cloud model-list validation timed out"
        ) from ex
    except requests.RequestException as ex:
        raise CredentialsValidateFailedError(
            "Unable to reach Radeon Cloud model list"
        ) from ex

    if response.status_code != HTTPStatus.OK:
        raise CredentialsValidateFailedError(
            f"Radeon Cloud model-list validation failed with status {response.status_code}"
        )
    if len(response.content) > MAX_MODELS_RESPONSE_BYTES:
        raise CredentialsValidateFailedError(
            "Radeon Cloud returned an oversized model list"
        )

    try:
        payload = response.json()
    except ValueError as ex:
        raise CredentialsValidateFailedError(
            "Radeon Cloud returned an invalid model list"
        ) from ex

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise CredentialsValidateFailedError(
            "Radeon Cloud returned an invalid model list"
        )

    model_ids = {
        item.get("id")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if model not in model_ids:
        raise CredentialsValidateFailedError(
            f"Model '{model}' is not available to this Radeon Cloud API key"
        )