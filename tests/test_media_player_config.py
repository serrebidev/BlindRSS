from core.config import DEFAULT_CONFIG
from core.vlc_options import build_vlc_instance_args


def test_default_preferred_soundcard_is_system_default():
    assert DEFAULT_CONFIG.get("preferred_soundcard", None) == ""


def test_vlc_instance_args_disable_plugin_cache():
    args = build_vlc_instance_args("--no-video", "--no-video", "--aout=directsound")

    assert args[0] == "--no-plugins-cache"
    assert args.count("--no-plugins-cache") == 1
    assert args.count("--no-video") == 1
    assert "--aout=directsound" in args
