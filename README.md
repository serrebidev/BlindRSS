  # BlindRSS

BlindRSS is a screen-reader-friendly desktop RSS and podcast app. It is built for fast feed reading and reliable audio playback.

## What BlindRSS Does

- Reads RSS/Atom feeds and plays podcast/video enclosures.
- Supports local feeds plus hosted providers: Miniflux, Inoreader, The Old Reader, and BazQux.
- Includes All/Unread/Read/Favorites views, plus mark read/unread and mark all read.
- Extracts full article text when feeds only provide summaries.
- Finds feeds from URLs and search providers (Apple Podcasts, gPodder, Feedly, NewsBlur, Reddit, Fediverse, Feedsearch, and local discovery).
- Supports YouTube, Rumble, and Odysee URL discovery/media handling through yt-dlp and local resolvers.
- Uses a local range-cache proxy for faster seeking and smoother VLC playback.
- Casts to Chromecast, DLNA/UPnP, and AirPlay.
- Supports tray controls, media keys, saved searches, and startup restore of your last selected feed/folder.
- Supports Windows notifications for new articles with per-feed exclusions and per-refresh limits.
- Includes a built-in updater that verifies SHA-256 and Authenticode before applying updates.

## I accept pull requests!

If BlindRSS has helped you, feel free to submit pull requests with fixes or features you want, and I will consider them.
## Quick Start
1. Download the latest `.zip` asset from [GitHub Releases](https://github.com/serrebi/BlindRSS/releases).
2. Extract the `.zip` anywhere.
3. Run `BlindRSS.exe`.

## Run From Python (Any OS)

1. Install Python 3.12+.
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python main.py`

## How to build
[`build.md`](build.md).
##Submit bugs in issues, or join my Telegram group!
(https://t.me/SerrebiProjects)
