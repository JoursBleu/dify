"""Deterministic request interleavings: no threads, sleeps or public requests."""

from unittest.mock import Mock

import pytest
import requests
from test_catalog import remote_model, response

import model_catalog as catalog


@pytest.fixture(autouse=True)
def empty_cache():
    catalog.clear_catalog_cache()
    yield
    catalog.clear_catalog_cache()


@pytest.mark.parametrize("status", [[], {}, ["online"], {"state": "online"}, True, 17])
def test_malformed_status_is_a_sanitized_catalog_error(status):
    with pytest.raises(catalog.CatalogUnavailableError, match="invalid model status"):
        catalog.parse_catalog({"data": [remote_model(status=status)]})


@pytest.mark.parametrize("newer_outcome", ["success", "failure", "clear"])
def test_old_writer_cannot_overwrite_or_repopulate_after_newer_operation(
    monkeypatch, newer_outcome
):
    def older_response(*args, **kwargs):
        # The older request has started, but has not yet received its response.
        if newer_outcome == "clear":
            catalog.clear_catalog_cache()
        elif newer_outcome == "failure":
            with pytest.raises(catalog.CatalogUnavailableError):
                catalog.fetch_catalog("rc-fixture", force_refresh=True)
        else:
            assert catalog.fetch_catalog("rc-fixture", force_refresh=True)[0]["model"] == "new"
        return response({"data": [remote_model("old")]})

    replies = iter([
        older_response,
        response({}, 503) if newer_outcome == "failure" else response({
            "data": [remote_model("new" if newer_outcome == "success" else "fresh")]
        }),
        response({"data": [remote_model("fresh")]}),
    ])

    def next_response(*args, **kwargs):
        reply = next(replies)
        return reply(*args, **kwargs) if reply is older_response else reply

    get = Mock(side_effect=next_response)
    monkeypatch.setattr(requests, "get", get)
    assert catalog.fetch_catalog("rc-fixture")[0]["model"] == "old"
    expected = "new" if newer_outcome == "success" else "fresh"
    assert catalog.fetch_catalog("rc-fixture")[0]["model"] == expected
    assert get.call_count == (3 if newer_outcome == "failure" else 2)


def test_older_failure_does_not_remove_newer_success(monkeypatch):
    def old_request(*args, **kwargs):
        assert catalog.fetch_catalog("rc-fixture", force_refresh=True)[0]["model"] == "new"
        return response({}, 503)

    get = Mock(side_effect=lambda *args, **kwargs: (
        old_request(*args, **kwargs) if get.call_count == 1
        else response({"data": [remote_model("new")]})
    ))
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(catalog.CatalogUnavailableError):
        catalog.fetch_catalog("rc-fixture")
    assert catalog.fetch_catalog("rc-fixture")[0]["model"] == "new"
    assert get.call_count == 2
    assert not catalog._pending


def test_clear_then_same_key_new_writer_prevents_aba(monkeypatch):
    def old_request(*args, **kwargs):
        catalog.clear_catalog_cache()
        assert catalog.fetch_catalog("rc-fixture")[0]["model"] == "new"
        return response({"data": [remote_model("old")]})

    get = Mock(side_effect=lambda *args, **kwargs: (
        old_request(*args, **kwargs) if get.call_count == 1
        else response({"data": [remote_model("new")]})
    ))
    monkeypatch.setattr(requests, "get", get)
    assert catalog.fetch_catalog("rc-fixture")[0]["model"] == "old"
    assert catalog.fetch_catalog("rc-fixture")[0]["model"] == "new"
    assert get.call_count == 2
    assert not catalog._pending


def test_writer_metadata_is_bounded_and_evicted_writers_cannot_republish(monkeypatch):
    monkeypatch.setattr(catalog, "MAX_CACHED_CREDENTIALS", 3)

    def nested_request(*args, **kwargs):
        index = get.call_count
        assert len(catalog._pending) <= 3
        assert len(catalog._cache) <= 3
        assert all(len(key) == 64 and "rc-" not in key for key in catalog._pending)
        if index < 10:
            catalog.fetch_catalog(f"rc-fixture-{index}")
        return response({"data": [remote_model(f"model-{index}")]})

    get = Mock(side_effect=nested_request)
    monkeypatch.setattr(requests, "get", get)
    catalog.fetch_catalog("rc-fixture-0")
    assert not catalog._pending
    assert len(catalog._cache) == 3
    assert {models[0]["model"] for _, models in catalog._cache.values()} == {
        "model-8", "model-9", "model-10",
    }
    assert catalog.fetch_catalog("rc-fixture-0")[0]["model"] == "model-11"


@pytest.mark.parametrize("failure", ["http", "connection", "parse", "close"])
def test_completed_failures_always_cleanup_writer_metadata(monkeypatch, failure):
    reply = response({"data": [remote_model(status=[])]} if failure == "parse" else {"data": []},
                     503 if failure == "http" else 200)
    if failure == "close":
        reply.close.side_effect = requests.ConnectionError("fixture close failure")
    get = Mock(side_effect=requests.ConnectionError("fixture")) if failure == "connection" else (
        Mock(return_value=reply)
    )
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(catalog.CatalogError):
        catalog.fetch_catalog("rc-fixture")
    assert not catalog._pending
    assert not catalog._cache


def test_expired_entries_are_cleaned_on_another_credential_lookup(monkeypatch):
    clock = Mock(return_value=0.0)
    monkeypatch.setattr(catalog.time, "monotonic", clock)
    monkeypatch.setattr(requests, "get", Mock(return_value=response({"data": []})))
    catalog.fetch_catalog("rc-old")
    clock.return_value = catalog.CACHE_TTL_SECONDS
    catalog.fetch_catalog("rc-new")
    assert len(catalog._cache) == 1
    assert not catalog._pending


def test_success_cache_is_bounded_under_many_completed_credentials(monkeypatch):
    monkeypatch.setattr(catalog, "MAX_CACHED_CREDENTIALS", 3)
    monkeypatch.setattr(requests, "get", Mock(return_value=response({"data": []})))
    for index in range(20):
        catalog.fetch_catalog(f"rc-fixture-{index}")
        assert len(catalog._cache) <= 3
        assert not catalog._pending
    catalog.clear_catalog_cache()
    assert not catalog._cache and not catalog._pending