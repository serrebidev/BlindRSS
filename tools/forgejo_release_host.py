#!/usr/bin/env python3
"""Forgejo release steps for build.bat on the Windows release host.

Stands in for the `gh` calls from when releases lived on GitHub (suspended).
Needs FORGEJO_TOKEN. Stdlib only.

    python tools/forgejo_release_host.py create-draft vX.Y.Z NOTES_FILE
    python tools/forgejo_release_host.py check-no-drafts
    python tools/forgejo_release_host.py dispatch-wait vX.Y.Z
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SERVER = os.environ.get("FORGEJO_URL", "https://git.serrebiradio.com").rstrip("/")
REPO = os.environ.get("FORGEJO_REPO", "serrebi/BlindRSS")
API = f"{SERVER}/api/v1/repos/{REPO}"
WORKFLOW = "cross-platform-release.yml"


def call(method, path, body=None):
    token = os.environ.get("FORGEJO_TOKEN") or sys.exit("FORGEJO_TOKEN is not set")
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                 headers={"Authorization": f"token {token}", "Accept": "application/json",
                                          **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {path}: HTTP {exc.code} {exc.read().decode('utf-8', 'replace')[:300]}")
    return json.loads(raw) if raw.strip() else None


def release(tag):
    return call("GET", f"/releases/tags/{urllib.parse.quote(tag, safe='')}")


def create_draft(tag, notes_file):
    with open(notes_file, encoding="utf-8") as f:
        notes = f.read()
    # Draft: the updater reads /releases/latest, which skips drafts, so users
    # never see a release that is still missing a platform.
    call("POST", "/releases", {"tag_name": tag, "name": tag, "body": notes, "draft": True, "prerelease": False})
    print(f"Created draft Forgejo release {tag}.")


def check_no_drafts():
    drafts = [r["tag_name"] for r in call("GET", "/releases?limit=50&draft=true") or [] if r.get("draft")]
    if drafts:
        print("Draft releases found:")
        for tag in drafts:
            print(f"  {tag}")
        sys.exit(1)


def dispatch_wait(tag):
    before = {r["id"] for r in (call("GET", "/actions/runs?limit=20") or {}).get("workflow_runs", [])}
    call("POST", f"/actions/workflows/{WORKFLOW}/dispatches",
         {"ref": "main", "inputs": {"release_tag": tag, "build_windows": "true", "build_linux": "false",
                                    "publish_assets": "true", "publish_release": "true"}})
    run_id = None
    for _ in range(24):
        time.sleep(5)
        runs = (call("GET", "/actions/runs?limit=20") or {}).get("workflow_runs", [])
        new = [r for r in runs if r["id"] not in before]
        if new:
            run_id = new[0]["id"]
            break
    if run_id is None:
        sys.exit(f"The dispatched {WORKFLOW} run did not appear. {tag} is still a draft.")
    print(f"Watching Forgejo run {run_id}.", flush=True)
    deadline = time.time() + 3 * 60 * 60
    while time.time() < deadline:
        run = call("GET", f"/actions/runs/{run_id}")
        status = run.get("status")
        if status in ("success", "failure", "cancelled", "skipped"):
            if status != "success":
                sys.exit(f"Forgejo run {run_id} ended {status}. {tag} is still a draft.")
            if release(tag).get("draft"):
                sys.exit(f"Run {run_id} succeeded but {tag} is still a draft.")
            print(f"Run {run_id} succeeded; {tag} is published.")
            return
        time.sleep(30)
    sys.exit(f"Forgejo run {run_id} still running after 3 hours. {tag} is still a draft.")


def main(argv):
    if not argv or argv[0] not in ("create-draft", "check-no-drafts", "dispatch-wait"):
        sys.exit(__doc__)
    if argv[0] == "create-draft":
        create_draft(argv[1], argv[2])
    elif argv[0] == "check-no-drafts":
        check_no_drafts()
    else:
        dispatch_wait(argv[1])


if __name__ == "__main__":
    main(sys.argv[1:])
