# BlindRSS

A screen-reader-friendly desktop RSS and podcast client for Windows, macOS, and Linux, built for fast feed reading and dependable audio playback.

[![Join SerrebiProjects on Telegram](https://img.shields.io/badge/Telegram-SerrebiProjects-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/SerrebiProjects)

**Have a question, hit a bug, or want early word on new releases?** Join the [SerrebiProjects Telegram group](https://t.me/SerrebiProjects) — the community hub for BlindRSS and my other projects, and the fastest place to get help.

## Features

- Reads RSS/Atom feeds and plays podcast and video enclosures.
- Works with local feeds and hosted providers: Miniflux, Inoreader, The Old Reader, and BazQux.
- All / Unread / Read / Favorites views, with mark read/unread and mark all read.
- Recovers full article text when a feed only ships summaries.
- Discovers feeds from URLs and search providers: Apple Podcasts, gPodder, Feedly, NewsBlur, Reddit, the Fediverse, Feedsearch, and local discovery.
- Resolves YouTube, Rumble, and Odysee media through yt-dlp and built-in resolvers.
- Smooths VLC playback and seeking with a local range-cache proxy.
- Casts to Chromecast, DLNA/UPnP, and AirPlay.
- Tray controls, media-key support, saved searches, and startup restore of your last feed and folder.
- Windows notifications for new articles, with per-feed exclusions and per-refresh limits.
- Built-in updater that verifies SHA-256 and Authenticode before applying an update.

## Download and install

Grab the latest build from the [Releases page](https://github.com/serrebidev/BlindRSS/releases).

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

## Community and support

Report bugs and request features in [Issues](https://github.com/serrebidev/BlindRSS/issues). For questions, feedback, and release news, join the [SerrebiProjects Telegram group](https://t.me/SerrebiProjects).
