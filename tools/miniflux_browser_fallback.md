# Miniflux direct-browser fallback

This optional companion is for a self-hosted Miniflux instance whose host is
served a JavaScript/browser challenge for some feed URLs. It is not an HTTP
proxy and does not mirror feed bodies. Hidden Chrome runs on the Miniflux host,
then Miniflux stores the matching cookie and User-Agent and continues fetching
the original feed URL directly.

BlindRSS discovers the service at the same Miniflux origin under
`/blindrss-browser-feed/v1`. If that path returns 404, the client disables the
capability probe for the rest of the process. An alternate same-origin base path
can be set as `providers.miniflux.browser_feed_fallback_path` in `config.json`.

## Server installation

1. Install Google Chrome and Python 3 with `venv` support.
2. Create `/opt/blindrss-feed-browser/venv` and install the same pinned runtime
   used by BlindRSS: `pip install seleniumbase==4.54.11`.
3. Copy `miniflux_browser_fallback_service.py` to
   `/opt/blindrss-feed-browser/service.py`.
4. Create the unprivileged `blindrss-browser` system account and writable
   `/var/lib/blindrss-miniflux-browser` directory owned by that account.
5. Install `miniflux-browser-fallback.service` under `/etc/systemd/system/`,
   then daemon-reload and enable/start `blindrss-miniflux-browser.service`.
6. Add `miniflux-browser-fallback.nginx.conf` to the Miniflux virtual host,
   validate with `nginx -t`, and reload Nginx.

The service listens only on `127.0.0.1:12794`. Nginx exposes the same-origin
path, while every add/recovery request must carry a valid Miniflux
`X-Auth-Token`; the service verifies that token through the local `/v1/me`
endpoint. Browser targets are limited to public HTTP(S) addresses to prevent
local/private-network access.

## Verification

- `curl http://127.0.0.1:12794/health` returns `{"ok": true}` on the host.
- An authenticated `POST /blindrss-browser-feed/v1/recover` returns HTTP 202.
- `journalctl -u blindrss-miniflux-browser.service` records recovery outcomes
  without logging API tokens or clearance-cookie values.
