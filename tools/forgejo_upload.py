#!/usr/bin/env python3
"""Attach files to a Forgejo release, replacing same-named assets.

    FORGEJO_TOKEN=... python tools/forgejo_upload.py vX.Y.Z file [file ...]

Stands in for `gh release upload TAG FILES --clobber`. The repository comes
from GITHUB_SERVER_URL and GITHUB_REPOSITORY (set in Forgejo Actions), or
FORGEJO_URL and FORGEJO_REPO. The release must already exist. Stdlib only.
"""
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def call(method, url, token, data=None, content_type=None):
    headers = {"Authorization": f"token {token}", "Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {url}: HTTP {exc.code} {exc.read().decode('utf-8', 'replace')[:300]}")
    return json.loads(body) if body else None


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    tag, files = argv[0], [Path(f) for f in argv[1:]]
    token = os.environ.get("FORGEJO_TOKEN") or sys.exit("FORGEJO_TOKEN is not set")
    server = os.environ.get("FORGEJO_URL") or os.environ.get("GITHUB_SERVER_URL") or "https://git.serrebiradio.com"
    repo = os.environ.get("FORGEJO_REPO") or os.environ.get("GITHUB_REPOSITORY") or sys.exit("No repository given")
    api = f"{server.rstrip('/')}/api/v1/repos/{repo}"
    release = call("GET", f"{api}/releases/tags/{urllib.parse.quote(tag, safe='')}", token)
    existing = {a["name"]: a["id"] for a in release.get("assets", [])}
    for path in files:
        if path.name in existing:
            call("DELETE", f"{api}/releases/{release['id']}/assets/{existing[path.name]}", token)
        boundary = uuid.uuid4().hex
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="attachment"; filename="{path.name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        call("POST", f"{api}/releases/{release['id']}/assets?name={urllib.parse.quote(path.name)}", token,
             body, f"multipart/form-data; boundary={boundary}")
        print(f"Attached {path.name} to {tag}")


if __name__ == "__main__":
    main(sys.argv[1:])
