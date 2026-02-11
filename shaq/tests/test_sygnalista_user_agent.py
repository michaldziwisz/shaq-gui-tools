from __future__ import annotations

import urllib.request

import shaq._sygnalista_gui as sygnalista_gui


def test_sygnalista_user_agent_format() -> None:
    assert sygnalista_gui._sygnalista_user_agent("shaqgui", "0.1.5") == "shaqgui/0.1.5 (sygnalista)"
    assert sygnalista_gui._sygnalista_user_agent("shaqgui", None) == "shaqgui (sygnalista)"


def test_install_urllib_user_agent_sets_global_opener() -> None:
    prev_opener = getattr(urllib.request, "_opener", None)
    try:
        sygnalista_gui._install_urllib_user_agent("test-agent/1.0")
        opener = getattr(urllib.request, "_opener", None)
        assert opener is not None

        user_agents = [value for (key, value) in opener.addheaders if key.lower() == "user-agent"]
        assert user_agents == ["test-agent/1.0"]
    finally:
        urllib.request.install_opener(prev_opener)

