"""Offline tests must explicitly mock transport; live tests remain opt-in."""

import pytest
import requests


@pytest.fixture(autouse=True)
def deny_unmocked_network(request, monkeypatch):
    if request.node.get_closest_marker("live") is not None:
        return

    def blocked(*args, **kwargs):
        raise AssertionError("Offline tests must not send unmocked HTTP requests")

    monkeypatch.setattr(requests.sessions.Session, "send", blocked)