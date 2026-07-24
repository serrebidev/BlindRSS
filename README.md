# BlindRSS

A vibe-coded, screen-reader-friendly desktop RSS and podcast client for Windows, macOS, and Linux, built for fast feed reading and dependable audio playback.

[![Join SerrebiProjects on Telegram](https://img.shields.io/badge/Telegram-SerrebiProjects-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/SerrebiProjects)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

**Have a question, hit a bug, or want early word on new releases?** Join the [SerrebiProjects Telegram group](https://t.me/SerrebiProjects) — the community hub for BlindRSS and my other projects, and the fastest place to get help.

## Features

- Reads RSS/Atom feeds and plays podcast and video enclosures.
- Works with local feeds and hosted providers: Miniflux, Inoreader, The Old Reader, and BazQux.
- All / Unread / Read / Favorites views, with mark read/unread and mark all read.
- Smart Folders, saved searches, and a Feeds with Errors view for feeds that quietly stopped updating.
- Filter rules that move, label, or delete articles as they arrive.
- Deleted Articles view that restores what you removed, and permanently deletes when you mean it.
- Recovers full article text when a feed only ships summaries.
- Reads YouTube videos as articles, with the description, transcript, and chapters inline.
- Reads Reddit, Lemmy, Groups.io, and Google Groups discussions as whole threads rather than one post.
- Discovers feeds from URLs and search providers: Apple Podcasts, gPodder, Feedly, NewsBlur, Feedspot, Reddit, the Fediverse, Feedsearch, and local discovery.
- Subscribes to YouTube channels and playlists, Mastodon, Bluesky, PieFed, SoundCloud, and Mixcloud.
- Imports subscriptions in bulk from OPML and from a YouTube Takeout export.
- Fetches feeds behind bot protection using a configurable browser identity and imported clearance cookies.
- Resolves YouTube, Rumble, and Odysee media through yt-dlp and built-in resolvers.
- Smooths VLC playback and seeking with a local range-cache proxy.
- Playback speed control, an equalizer, silence skipping, chapters, and soundcard selection.
- Casts to Chromecast, DLNA/UPnP, and AirPlay.
- Tray controls, media-key support, and startup restore of your last feed and folder.
- Windows notifications for new articles, with per-feed exclusions and per-refresh limits.
- 61 remappable keyboard commands, grouped by feeds, articles, view, player, and playback speed.
- Translated into 15 languages, with catalog updates delivered between app releases.
- Built-in updater that verifies SHA-256 and Authenticode before applying an update.

## Download and install

Grab the latest build from the [Releases page](https://github.com/serrebidev/BlindRSS/releases).
For a version-by-version history, see the [changelog](CHANGELOG.md).

**Windows installer (recommended)**

1. Download `BlindRSS-Setup-vX.Y.Z.exe`.
2. Run it and approve the elevation prompt. It installs to Program Files, adds a Start Menu entry, and updates itself in place.

**Windows portable**

1. Download `BlindRSS-vX.Y.Z.zip`.
2. Extract it anywhere and run `BlindRSS.exe` — no installation required.

**macOS and Linux**

Download the matching `…-macos.zip` or `…-linux.tar.gz` asset from the same release.

Installed builds keep your settings and database in `%APPDATA%\BlindRSS` and default episode downloads to your Downloads folder. Uninstalling leaves your data untouched.

## Run from source (any OS)

1. Install Python 3.14.
2. Install dependencies: `pip install -r requirements.txt`
3. Launch it: `python main.py`

## Building

See [`build.md`](build.md) for the full release pipeline — PyInstaller packaging, Authenticode signing, the Program Files installer, and the macOS/Linux build dispatch.

## Debug logging

Enable debug mode in Settings to write a rotating `blindrss.log` (DEBUG and above) next to your config and data. With debug mode off, no log file is created.

## Contributing

Pull requests are welcome. If BlindRSS has been useful to you, open a PR with a fix or feature and I'll review it.

## Translations

I only speak English, so I got several languages started with AI-assisted translation rather than leaving them untranslated. Human translation is always preferred, and I'd rather have a native speaker's review than a machine's best guess.

If you speak one of the supported languages and something reads wrong, awkward, or just off, please open a PR to fix it — I can't judge the wording myself, so I'll almost certainly accept it. See [`locale/README.md`](locale/README.md) for how the translation files are laid out and how to update them.

## License

BlindRSS is under the [MIT license](LICENSE) — use it, change it, redistribute it, or package it for a distro repository, no permission needed. Every source file carries an `SPDX-License-Identifier: MIT` header so packaging tools can pick the license up automatically.

It went unlicensed longer than it should have, which quietly blocked anyone trying to package it. If that was you, it's sorted now.

## Community and support

Report bugs and request features in [Issues](https://github.com/serrebidev/BlindRSS/issues). For questions, feedback, and release news, join the [SerrebiProjects Telegram group](https://t.me/SerrebiProjects).
