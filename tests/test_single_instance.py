import threading

from core import single_instance


def test_relaunch_activates_running_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(single_instance, "_state_path", lambda: str(tmp_path / "state.json"))
    hit = threading.Event()
    server = single_instance.serve(hit.set)
    try:
        assert server is not None
        assert single_instance.activate_existing()
        assert hit.wait(5)
    finally:
        server.close()


def test_wrong_token_is_ignored(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setattr(single_instance, "_state_path", lambda: str(path))
    hit = threading.Event()
    server = single_instance.serve(hit.set)
    try:
        path.write_text(path.read_text().replace('"token": "', '"token": "x'))
        single_instance.activate_existing()
        assert not hit.wait(0.5)
    finally:
        server.close()


def test_no_running_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(single_instance, "_state_path", lambda: str(tmp_path / "missing.json"))
    assert single_instance.activate_existing() is False
