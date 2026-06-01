import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import play_cache


class _FakeConfig:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)


def _mk(cache, name, size, mtime):
    p = os.path.join(cache, name)
    with open(p, "wb") as fh:
        fh.write(b"\x00" * size)
    os.utime(p, (mtime, mtime))
    return p


def test_resolve_cache_dir_prefers_custom(tmp_path):
    custom = os.path.join(str(tmp_path), "mycache")
    cfg = _FakeConfig({"youtube_play_cache_dir": custom})
    assert play_cache.resolve_cache_dir(cfg) == custom


def test_resolve_cache_dir_falls_back_to_default(monkeypatch):
    cfg = _FakeConfig({"youtube_play_cache_dir": ""})
    monkeypatch.setattr(play_cache, "default_cache_dir", lambda: "/tmp/blindrss-default")
    assert play_cache.resolve_cache_dir(cfg) == "/tmp/blindrss-default"


def test_size_and_count_ignore_partials(tmp_path):
    cache = str(tmp_path)
    _mk(cache, "a.m4a", 100, 1000)
    _mk(cache, "b.m4a", 200, 1001)
    _mk(cache, "c.m4a.part", 999, 1002)  # ignored
    assert play_cache.cache_file_count(cache) == 2
    assert play_cache.cache_size_bytes(cache) == 300


def test_clear_cache_removes_everything_including_partials(tmp_path):
    cache = str(tmp_path)
    _mk(cache, "a.m4a", 100, 1000)
    _mk(cache, "b.m4a.part", 50, 1001)
    removed, freed = play_cache.clear_cache(cache)
    assert removed == 2
    assert freed == 150
    assert os.listdir(cache) == []


def test_prune_cache_drops_oldest_until_under_cap(tmp_path):
    cache = str(tmp_path)
    # 3 files x 1 MB each, distinct ages.
    one_mb = 1024 * 1024
    _mk(cache, "old.m4a", one_mb, 1000)
    _mk(cache, "mid.m4a", one_mb, 2000)
    _mk(cache, "new.m4a", one_mb, 3000)
    # Cap at 2 MB -> newest two kept, oldest removed.
    removed = play_cache.prune_cache(cache, 2)
    assert removed == 1
    remaining = sorted(os.listdir(cache))
    assert remaining == ["mid.m4a", "new.m4a"]


def test_prune_cache_unlimited_when_zero(tmp_path):
    cache = str(tmp_path)
    _mk(cache, "a.m4a", 1024 * 1024, 1000)
    assert play_cache.prune_cache(cache, 0) == 0
    assert os.listdir(cache) == ["a.m4a"]


def test_prune_cache_missing_dir_is_safe(tmp_path):
    missing = os.path.join(str(tmp_path), "nope")
    assert play_cache.prune_cache(missing, 100) == 0
    assert play_cache.cache_size_bytes(missing) == 0
    assert play_cache.clear_cache(missing) == (0, 0)


def test_human_size():
    assert play_cache.human_size(0) == "0 B"
    assert play_cache.human_size(512) == "512 B"
    assert play_cache.human_size(1536) == "1.5 KB"
    assert play_cache.human_size(5 * 1024 * 1024) == "5.0 MB"
