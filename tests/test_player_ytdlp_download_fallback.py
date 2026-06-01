import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("wx")
pytest.importorskip("vlc")

from gui.player import PlayerFrame


def _bare_player():
    # Build without running the heavy wx/vlc __init__; the methods under test are
    # pure and only use their arguments plus a couple of cheap attributes.
    return PlayerFrame.__new__(PlayerFrame)


def test_resolve_printed_filepath_prefers_printed_line(tmp_path):
    p = _bare_player()
    f = os.path.join(str(tmp_path), "abc123.m4a")
    with open(f, "wb") as fh:
        fh.write(b"\x00\x00")
    stdout = f"[info] Downloading\n{f}\n"
    assert p._resolve_printed_filepath(stdout, str(tmp_path)) == f


def test_resolve_printed_filepath_falls_back_to_newest_in_dir(tmp_path):
    p = _bare_player()
    older = os.path.join(str(tmp_path), "old.m4a")
    newer = os.path.join(str(tmp_path), "new.m4a")
    for path in (older, newer):
        with open(path, "wb") as fh:
            fh.write(b"\x00")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    # No valid path printed -> newest file in the cache dir wins.
    assert p._resolve_printed_filepath("nothing useful here\n", str(tmp_path)) == newer


def test_resolve_printed_filepath_ignores_partial_when_scanning(tmp_path):
    p = _bare_player()
    part = os.path.join(str(tmp_path), "x.m4a.part")
    with open(part, "wb") as fh:
        fh.write(b"\x00")
    assert p._resolve_printed_filepath("", str(tmp_path)) is None


def test_prune_ytplay_cache_keeps_newest(tmp_path, monkeypatch):
    p = _bare_player()
    cache = str(tmp_path)
    monkeypatch.setattr(p, "_ytdlp_play_cache_dir", lambda: cache)
    paths = []
    for i in range(9):
        fp = os.path.join(cache, f"f{i}.m4a")
        with open(fp, "wb") as fh:
            fh.write(b"\x00")
        os.utime(fp, (1000 + i, 1000 + i))
        paths.append(fp)
    p._prune_ytplay_cache(keep=3)
    remaining = sorted(n for n in os.listdir(cache))
    # Only the 3 newest survive.
    assert remaining == ["f6.m4a", "f7.m4a", "f8.m4a"]


def test_maybe_play_ytdlp_via_download_declines_when_not_ytdlp():
    p = _bare_player()
    p._active_load_seq = 5
    p._current_use_ytdlp = False
    p._ytdlp_page_url = "https://www.youtube.com/watch?v=x"
    p._ytdlp_download_fallback_tried = False
    assert p.maybe_play_ytdlp_via_download(5) is False


def test_maybe_play_ytdlp_via_download_declines_on_stale_seq():
    p = _bare_player()
    p._active_load_seq = 7
    p._current_use_ytdlp = True
    p._ytdlp_page_url = "https://www.youtube.com/watch?v=x"
    p._ytdlp_download_fallback_tried = False
    # A superseded load must not start a download.
    assert p.maybe_play_ytdlp_via_download(6) is False


def test_maybe_play_ytdlp_via_download_declines_when_already_tried():
    p = _bare_player()
    p._active_load_seq = 7
    p._current_use_ytdlp = True
    p._ytdlp_page_url = "https://www.youtube.com/watch?v=x"
    p._ytdlp_download_fallback_tried = True
    assert p.maybe_play_ytdlp_via_download(7) is False
