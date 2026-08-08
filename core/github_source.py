# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Complete-page readers for GitHub pull requests, issues, commits and releases.

GitHub's own HTML is a JavaScript application: the conversation timeline, the
review threads and the commit list are hydrated after load, while the diff is
server-rendered as a table.  Generic article extraction therefore came back with
the diff table alone — the description, every comment and every review were lost
(reported for pull-request pages, but the same is true of issues and commits).

The REST API exposes all of it, already rendered to HTML when asked with the
``full`` media type.  This module rebuilds one semantic document in the same
small vocabulary the Reddit/Lemmy/Groups.io readers use
(``section.blindrss-github-post`` + ``.blindrss-github-body``), so the classic
text reader linearizes it through the shared forum linearizer and the rich
reader renders it without a trafilatura prune.

Everything fails closed: when the API is unreachable, rate limited, or the URL
is a page shape we do not model (a repository home page, a discussion), the
caller falls back to the ordinary HTML fetch chain and behavior is unchanged.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote, urlencode, urlsplit

from core import config as config_mod
from core import utils


log = logging.getLogger(__name__)

_API_ROOT = "https://api.github.com"
_API_VERSION = "2022-11-28"
# The "full" media type adds body_html (GitHub-rendered Markdown) next to the
# raw body, so comments keep their links, lists, code blocks and images without
# BlindRSS having to render Markdown itself.
_ACCEPT_FULL = "application/vnd.github.full+json"

_GITHUB_HOSTS = ("github.com", "www.github.com")
# Path segments that are never a repository name, so "/orgs/foo/issues" and
# friends can't be read as owner/repo.
_RESERVED_OWNERS = {
    "about", "apps", "blog", "collections", "contact", "customer-stories",
    "enterprise", "events", "explore", "features", "issues", "login",
    "marketplace", "notifications", "orgs", "pricing", "pulls", "search",
    "security", "settings", "site", "sponsors", "stars", "topics", "trending",
    "users", "watching",
}

_OWNER_REPO = r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?)/(?P<repo>[A-Za-z0-9._-]{1,100})"
_PULL_RE = re.compile(
    rf"^/{_OWNER_REPO}/pull/(?P<number>\d+)(?:/(?:files|commits|checks|conversation)(?:/[^/]*)?)?/?$"
)
_ISSUE_RE = re.compile(rf"^/{_OWNER_REPO}/issues/(?P<number>\d+)/?$")
_COMMIT_RE = re.compile(rf"^/{_OWNER_REPO}/commit/(?P<sha>[0-9a-fA-F]{{7,40}})(?:\.patch|\.diff)?/?$")
_RELEASE_RE = re.compile(rf"^/{_OWNER_REPO}/releases/tag/(?P<tag>[^/]+)/?$")
_DISCUSSION_RE = re.compile(rf"^/{_OWNER_REPO}/discussions/(?P<number>\d+)/?$")
# Organization-level discussions ("github.com/orgs/community/discussions/1234")
# live in the org's .github repository, which is what the API reads.
_ORG_DISCUSSION_RE = re.compile(
    r"^/orgs/(?P<owner>[A-Za-z0-9][A-Za-z0-9._-]{0,99})/discussions/(?P<number>\d+)/?$"
)

# Bounds. A busy pull request can carry thousands of review comments and a
# refactor can touch hundreds of files; the reader must stay finite without
# silently dropping the discussion, which is the content this module exists to
# recover, so the generous caps are on the discussion and the tight ones are on
# the diff.
_MAX_API_PAGES = 20
_MAX_COMMENTS = 2000
_MAX_COMMITS = 250
_MAX_FILES = 300
_MAX_DIFF_FILES = 60
_MAX_DIFF_LINES_PER_FILE = 400
_MAX_DIFF_LINES_TOTAL = 4000
_MAX_HUNK_CONTEXT_LINES = 6


@dataclass(frozen=True)
class GitHubTarget:
    """A GitHub page shape this module can rebuild."""

    kind: str  # "pull" | "issue" | "commit" | "release" | "discussion" | "org_discussion"
    owner: str
    repo: str
    ref: str  # issue/PR/discussion number, commit sha, or release tag

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}" if self.repo else self.owner

    @property
    def canonical_url(self) -> str:
        if self.kind == "org_discussion":
            return f"https://github.com/orgs/{self.owner}/discussions/{self.ref}"
        path = {
            "pull": f"pull/{self.ref}",
            "issue": f"issues/{self.ref}",
            "commit": f"commit/{self.ref}",
            "release": f"releases/tag/{quote(self.ref, safe='')}",
            "discussion": f"discussions/{self.ref}",
        }[self.kind]
        return f"https://github.com/{self.owner}/{self.repo}/{path}"


def parse_target(url: str) -> Optional[GitHubTarget]:
    """Return the GitHub page this URL identifies, or None when unsupported."""
    try:
        parts = urlsplit(str(url or "").strip())
    except Exception:
        return None
    if (parts.scheme or "").lower() not in ("http", "https"):
        return None
    if (parts.hostname or "").lower() not in _GITHUB_HOSTS:
        return None
    path = parts.path or ""
    # Organization discussions (the GitHub Community forum) have no repository and
    # no REST endpoint; they are rebuilt from the page, which GitHub does render
    # server-side. Checked before the reserved-owner rule below, which exists to
    # stop "/orgs/..." being read as owner/repo.
    org = _ORG_DISCUSSION_RE.match(path)
    if org:
        return GitHubTarget(
            kind="org_discussion", owner=org.group("owner"), repo="", ref=org.group("number")
        )
    for kind, pattern, group in (
        ("pull", _PULL_RE, "number"),
        ("issue", _ISSUE_RE, "number"),
        ("commit", _COMMIT_RE, "sha"),
        ("release", _RELEASE_RE, "tag"),
        ("discussion", _DISCUSSION_RE, "number"),
    ):
        match = pattern.match(path)
        if not match:
            continue
        owner = match.group("owner")
        repo = match.group("repo")
        if owner.lower() in _RESERVED_OWNERS:
            return None
        if repo.endswith(".git"):
            repo = repo[:-4]
        return GitHubTarget(kind=kind, owner=owner, repo=repo, ref=match.group(group))
    return None


def is_github_page_url(url: str) -> bool:
    """Whether ``url`` is a GitHub page this module rebuilds from the API."""
    return parse_target(url) is not None


def _token() -> str:
    """Return a personal access token from the environment or settings.

    Anonymous API access is 60 requests/hour per IP, which one busy GitHub feed
    can exhaust; a token raises that to 5000 and is the only way private
    repositories can be read at all. Absent, everything still works anonymously.
    """
    for name in ("BLINDRSS_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    try:
        with open(config_mod.CONFIG_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return str(data.get("github_token", "") or "").strip() if isinstance(data, dict) else ""
    except (OSError, ValueError, TypeError):
        return ""


def _api_get(path: str, *, timeout: float, params: Optional[dict] = None, accept: str = _ACCEPT_FULL):
    """GET an api.github.com resource, returning parsed JSON or None.

    Returns None (never raises) on any error, including the 403/429 rate-limit
    responses, so the caller degrades to the ordinary page fetch instead of
    showing an error where an article used to be.
    """
    url = _API_ROOT + path
    if params:
        url += "?" + urlencode(params)
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": _API_VERSION,
    }
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        # site_cookies=False: an API we call with our own credentials must not
        # receive the user's imported github.com browser session.
        response = utils.safe_requests_get(
            url, timeout=max(1.0, float(timeout or 20)), headers=headers,
            allow_redirects=True, site_cookies=False,
        )
    except Exception:
        log.debug("GitHub API request failed for %s", path, exc_info=True)
        return None
    status = int(getattr(response, "status_code", 0) or 0)
    if status != 200:
        if status in (403, 429):
            log.info("GitHub API rate limited or forbidden for %s", path)
        return None
    try:
        return response.json()
    except Exception:
        log.debug("GitHub API returned non-JSON for %s", path, exc_info=True)
        return None


def _api_list(path: str, *, timeout: float, max_items: int, accept: str = _ACCEPT_FULL) -> list:
    """Page through a list endpoint until it is exhausted or the cap is hit."""
    out: list = []
    per_page = 100
    for page in range(1, _MAX_API_PAGES + 1):
        data = _api_get(
            path, timeout=timeout, params={"per_page": per_page, "page": page}, accept=accept
        )
        if not isinstance(data, list) or not data:
            break
        out.extend(item for item in data if isinstance(item, dict))
        if len(data) < per_page or len(out) >= max_items:
            break
    return out[:max_items]


def _time_label(value: object) -> str:
    """Format a GitHub ISO-8601 timestamp as "2026-08-07 14:05 UTC"."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _sub_dict(obj: object, key: str) -> dict:
    """Return ``obj[key]`` when it is a dict, else an empty dict."""
    value = obj.get(key) if isinstance(obj, dict) else None
    return value if isinstance(value, dict) else {}


def _sub_list(obj: object, key: str) -> list:
    """Return ``obj[key]`` when it is a list, else an empty list."""
    value = obj.get(key) if isinstance(obj, dict) else None
    return value if isinstance(value, list) else []


def _int_field(obj: object, key: str) -> int:
    value = obj.get(key) if isinstance(obj, dict) else None
    return value if isinstance(value, int) else 0


def _login(obj: object) -> str:
    """Return the GitHub account that wrote something.

    Comments and pull requests carry the account under ``user``; releases and
    commits carry it under ``author``. "ghost" is GitHub's own name for content
    whose account is gone, and doubles as the signal to fall back to a git
    author name where one exists.
    """
    if isinstance(obj, dict):
        for key in ("user", "author"):
            holder = _sub_dict(obj, key)
            name = str(holder.get("login") or "").strip() if holder else ""
            if name:
                return name
        name = str(obj.get("login") or "").strip()
        if name:
            return name
    return "ghost"


def _plain_text_html(text: str) -> str:
    """Render plain text (commit messages, unrendered bodies) as safe HTML."""
    blocks = [block for block in re.split(r"\n\s*\n", str(text or "").strip()) if block.strip()]
    return "".join(
        "<p>" + "<br>".join(html.escape(line) for line in block.splitlines()) + "</p>"
        for block in blocks
    )


def _body_html(obj: object) -> str:
    """Return a comment/description body as HTML, whichever form the API gave."""
    if not isinstance(obj, dict):
        return ""
    rendered = str(obj.get("body_html") or "").strip()
    if rendered:
        return rendered
    return _plain_text_html(obj.get("body") or "")


def _escape(value: object) -> str:
    return html.escape(str(value or ""))


def _link(url: str, label: str) -> str:
    return f'<a href="{html.escape(str(url or ""), quote=True)}">{_escape(label)}</a>'


def _bullets(items: list) -> str:
    rows = "".join(f"<li>{item}</li>" for item in items if item)
    return f"<ul>{rows}</ul>" if rows else ""


def _pre_block(lines: list) -> str:
    """Render code lines as a <pre> whose line breaks survive both readers.

    The breaks are ``<br>``, not newlines: the plain-text converter collapses
    whitespace inside every text node (so a newline-separated <pre> arrives as
    one endless line) but turns each ``<br>`` into a real line break. The rich
    reader renders both identically.
    """
    return "<pre>" + "<br>".join(html.escape(line) for line in lines) + "</pre>"


def _diff_pre(patch: str, *, max_lines: int) -> tuple[str, int]:
    """Render a unified diff as a <pre> block, returning (html, lines used)."""
    lines = str(patch or "").splitlines()
    if not lines:
        return "", 0
    shown = lines[:max_lines]
    body = _pre_block(shown)
    trailer = ""
    if len(lines) > len(shown):
        trailer = f"<p>[Diff truncated: {len(lines) - len(shown)} more lines. Open the page on GitHub for the rest.]</p>"
    return f"{body}{trailer}", len(shown)


def _section(index: int, heading: str, body_html: str) -> str:
    return (
        '<section class="blindrss-github-post">'
        f"<h2>{_escape(f'#{index} {heading}'.strip())}</h2>"
        f'<div class="blindrss-github-body">{body_html or "<p>[no text available]</p>"}</div>'
        "</section>"
    )


def _document(title: str, canonical_url: str, author: str, sections: list) -> str:
    if not sections:
        return ""
    safe_title = _escape(title or "GitHub")
    meta_author = (
        f'<meta name="author" content="{html.escape(str(author), quote=True)}">' if author else ""
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{safe_title}</title>{meta_author}</head><body>"
        f"<h1>{safe_title}</h1>"
        f'<p>{_link(canonical_url, "Open this page on GitHub")}</p>'
        + "".join(sections)
        + "</body></html>"
    )


def _state_label(pull: dict) -> str:
    state = str(pull.get("state") or "").strip().lower()
    if pull.get("merged") or pull.get("merged_at"):
        return "Merged"
    if state == "closed":
        return "Closed"
    if pull.get("draft"):
        return "Draft"
    return "Open" if state == "open" else (state.capitalize() or "Unknown state")


def _name_list(values: object, key: str = "name") -> str:
    names = []
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict):
                label = str(item.get(key) or item.get("login") or "").strip()
            else:
                label = str(item or "").strip()
            if label:
                names.append(label)
    return ", ".join(names)


def _issue_summary_bullets(issue: dict, target: GitHubTarget) -> list:
    bullets = []
    labels = _name_list(issue.get("labels"))
    if labels:
        bullets.append(f"Labels: {_escape(labels)}")
    assignees = _name_list(issue.get("assignees"), key="login")
    if assignees:
        bullets.append(f"Assignees: {_escape(assignees)}")
    milestone = issue.get("milestone")
    if isinstance(milestone, dict) and milestone.get("title"):
        bullets.append(f"Milestone: {_escape(milestone.get('title'))}")
    closed = _time_label(issue.get("closed_at"))
    if closed:
        bullets.append(f"Closed: {_escape(closed)}")
    bullets.append(f"Repository: {_link(f'https://github.com/{target.slug}', target.slug)}")
    return bullets


def _pull_summary_bullets(pull: dict, target: GitHubTarget) -> list:
    base = _sub_dict(pull, "base")
    head = _sub_dict(pull, "head")
    bullets = [f"State: {_escape(_state_label(pull))}"]
    if base.get("ref") or head.get("label"):
        bullets.append(
            f"Merges {_escape(head.get('label') or head.get('ref') or '?')} "
            f"into {_escape(base.get('ref') or '?')}"
        )
    stats = []
    for key, label in (
        ("commits", "commit"),
        ("changed_files", "file changed"),
        ("additions", "addition"),
        ("deletions", "deletion"),
    ):
        value = pull.get(key)
        if isinstance(value, int):
            plural = "" if value == 1 else "s"
            if label == "file changed":
                stats.append(f"{value} file{plural} changed")
            else:
                stats.append(f"{value} {label}{plural}")
    if stats:
        bullets.append(_escape(", ".join(stats)))
    merged = _time_label(pull.get("merged_at"))
    if merged:
        merged_by = pull.get("merged_by")
        who = str(merged_by.get("login") or "").strip() if isinstance(merged_by, dict) else ""
        bullets.append(f"Merged: {_escape(merged + (f' by {who}' if who else ''))}")
    bullets.extend(_issue_summary_bullets(pull, target))
    return bullets


def _timeline_sections(events: list, start_index: int) -> tuple[list, int]:
    """Render sorted conversation events into numbered sections."""
    sections = []
    index = start_index
    for event in events:
        sections.append(_section(index, event["heading"], event["body"]))
        index += 1
    return sections, index


def _sort_key(event: dict) -> tuple:
    return (str(event.get("created") or ""), int(event.get("order") or 0))


def _comment_events(comments: list, label: str) -> list:
    events = []
    for order, comment in enumerate(comments):
        body = _body_html(comment)
        if not body.strip():
            continue
        when = _time_label(comment.get("created_at") or comment.get("submitted_at"))
        heading = f"{label} by {_login(comment)}"
        if when:
            heading += f" — {when}"
        events.append({
            "created": comment.get("created_at") or comment.get("submitted_at") or "",
            "order": order,
            "heading": heading,
            "body": body,
        })
    return events


def _review_events(reviews: list) -> list:
    """Review submissions ("Approved", "Changes requested") with their bodies."""
    states = {
        "APPROVED": "approved",
        "CHANGES_REQUESTED": "requested changes",
        "COMMENTED": "commented",
        "DISMISSED": "review dismissed",
    }
    events = []
    for order, review in enumerate(reviews):
        state = str(review.get("state") or "").strip().upper()
        if state == "PENDING":
            continue
        body = _body_html(review)
        verdict = states.get(state, state.replace("_", " ").lower() or "reviewed")
        # A bodyless "commented" review is only the container GitHub creates for
        # inline comments, which are rendered separately — it would read as an
        # empty post.
        if not body.strip() and state in ("COMMENTED", "DISMISSED"):
            continue
        when = _time_label(review.get("submitted_at"))
        heading = f"Review by {_login(review)} — {verdict}"
        if when:
            heading += f" — {when}"
        events.append({
            "created": review.get("submitted_at") or "",
            "order": order,
            "heading": heading,
            "body": body or f"<p>{_escape(_login(review).capitalize())} {_escape(verdict)}.</p>",
        })
    return events


def _review_comment_events(comments: list) -> list:
    """Inline code review comments, each with the line it was left on."""
    events = []
    for order, comment in enumerate(comments):
        body = _body_html(comment)
        if not body.strip():
            continue
        path = str(comment.get("path") or "").strip()
        line = comment.get("line") or comment.get("original_line") or comment.get("position")
        where = path
        if path and line:
            where = f"{path} line {line}"
        heading = f"Review comment by {_login(comment)}"
        if where:
            heading += f" on {where}"
        if comment.get("in_reply_to_id"):
            heading += " — reply"
        when = _time_label(comment.get("created_at"))
        if when:
            heading += f" — {when}"
        context = ""
        hunk = str(comment.get("diff_hunk") or "").strip()
        if hunk:
            lines = hunk.splitlines()[-_MAX_HUNK_CONTEXT_LINES:]
            context = (
                "<p>Code the comment is attached to:</p><pre>"
                + "\n".join(html.escape(entry) for entry in lines)
                + "</pre>"
            )
        events.append({
            "created": comment.get("created_at") or "",
            "order": order,
            "heading": heading,
            "body": context + body,
        })
    return events


def _files_sections(files: list, start_index: int, *, changed_label: str) -> list:
    """A changed-files summary, then one section per file diff (bounded)."""
    if not files:
        return []
    sections = []
    index = start_index
    rows = []
    for entry in files:
        name = str(entry.get("filename") or "").strip() or "(unnamed file)"
        status = str(entry.get("status") or "").strip() or "modified"
        added = _int_field(entry, "additions")
        removed = _int_field(entry, "deletions")
        previous = str(entry.get("previous_filename") or "").strip()
        label = f"{name} — {status}, {added} added, {removed} removed"
        if previous:
            label += f" (was {previous})"
        rows.append(_escape(label))
    sections.append(
        _section(index, f"{changed_label} ({len(files)})", _bullets(rows))
    )
    index += 1

    used = 0
    rendered = 0
    with_patch = [entry for entry in files if str(entry.get("patch") or "").strip()]
    for entry in with_patch[:_MAX_DIFF_FILES]:
        if used >= _MAX_DIFF_LINES_TOTAL:
            break
        budget = min(_MAX_DIFF_LINES_PER_FILE, _MAX_DIFF_LINES_TOTAL - used)
        block, lines_used = _diff_pre(str(entry.get("patch") or ""), max_lines=budget)
        if not block:
            continue
        used += lines_used
        rendered += 1
        name = str(entry.get("filename") or "").strip() or "(unnamed file)"
        sections.append(_section(index, f"Diff: {name}", block))
        index += 1

    # Never drop diffs silently: the reader must be able to tell "that is the whole
    # change" from "the rest is on the page".
    dropped = len(with_patch) - rendered
    if dropped > 0:
        sections.append(_section(
            index,
            "Remaining diffs not shown",
            f"<p>{_escape(f'{dropped} more changed files are not included here (the diff is too large to read in full). Open the page on GitHub to see them.')}</p>",
        ))
    return sections


def _pull_document(target: GitHubTarget, *, timeout: float) -> str:
    base = f"/repos/{quote(target.owner, safe='')}/{quote(target.repo, safe='')}"
    pull = _api_get(f"{base}/pulls/{target.ref}", timeout=timeout)
    if not isinstance(pull, dict) or not pull.get("number"):
        return ""

    title = str(pull.get("title") or "").strip() or f"Pull request #{target.ref}"
    author = _login(pull)
    opened = _time_label(pull.get("created_at"))
    heading = f"Pull request opened by {author}"
    if opened:
        heading += f" — {opened}"

    lead = _bullets(_pull_summary_bullets(pull, target)) + _body_html(pull)
    sections = [_section(1, heading, lead)]
    index = 2

    commits = _api_list(f"{base}/pulls/{target.ref}/commits", timeout=timeout, max_items=_MAX_COMMITS)
    if commits:
        rows = []
        for commit in commits:
            info = _sub_dict(commit, "commit")
            message = str(info.get("message") or "").strip().splitlines()
            subject = message[0] if message else "(no commit message)"
            sha = str(commit.get("sha") or "")[:7]
            who = _login(commit)
            if who == "ghost":
                author_info = _sub_dict(info, "author")
                who = str(author_info.get("name") or "").strip() or "unknown"
            rows.append(_escape(f"{sha} {subject} — {who}"))
        sections.append(_section(index, f"Commits ({len(commits)})", _bullets(rows)))
        index += 1

    events = []
    events.extend(_comment_events(
        _api_list(f"{base}/issues/{target.ref}/comments", timeout=timeout, max_items=_MAX_COMMENTS),
        "Comment",
    ))
    events.extend(_review_events(
        _api_list(f"{base}/pulls/{target.ref}/reviews", timeout=timeout, max_items=_MAX_COMMENTS)
    ))
    events.extend(_review_comment_events(
        _api_list(f"{base}/pulls/{target.ref}/comments", timeout=timeout, max_items=_MAX_COMMENTS)
    ))
    events.sort(key=_sort_key)
    timeline, index = _timeline_sections(events, index)
    sections.extend(timeline)

    files = _api_list(f"{base}/pulls/{target.ref}/files", timeout=timeout, max_items=_MAX_FILES)
    sections.extend(_files_sections(files, index, changed_label="Changed files"))

    return _document(f"{title} ({target.slug}#{target.ref})", target.canonical_url, author, sections)


def _issue_document(target: GitHubTarget, *, timeout: float) -> str:
    base = f"/repos/{quote(target.owner, safe='')}/{quote(target.repo, safe='')}"
    issue = _api_get(f"{base}/issues/{target.ref}", timeout=timeout)
    if not isinstance(issue, dict) or not issue.get("number"):
        return ""
    # /issues/N also serves pull requests; use the richer pull renderer for those
    # so a PR reached through an issue-style URL still shows its diff and reviews.
    if _sub_dict(issue, "pull_request"):
        pull_target = GitHubTarget("pull", target.owner, target.repo, target.ref)
        document = _pull_document(pull_target, timeout=timeout)
        if document:
            return document

    title = str(issue.get("title") or "").strip() or f"Issue #{target.ref}"
    author = _login(issue)
    opened = _time_label(issue.get("created_at"))
    state = "Closed" if str(issue.get("state") or "").lower() == "closed" else "Open"
    heading = f"Issue opened by {author}"
    if opened:
        heading += f" — {opened}"
    heading += f" — {state}"

    lead = _bullets(_issue_summary_bullets(issue, target)) + _body_html(issue)
    sections = [_section(1, heading, lead)]
    events = _comment_events(
        _api_list(f"{base}/issues/{target.ref}/comments", timeout=timeout, max_items=_MAX_COMMENTS),
        "Comment",
    )
    events.sort(key=_sort_key)
    sections.extend(_timeline_sections(events, 2)[0])
    return _document(f"{title} ({target.slug}#{target.ref})", target.canonical_url, author, sections)


def _commit_document(target: GitHubTarget, *, timeout: float) -> str:
    base = f"/repos/{quote(target.owner, safe='')}/{quote(target.repo, safe='')}"
    commit = _api_get(f"{base}/commits/{target.ref}", timeout=timeout)
    if not isinstance(commit, dict) or not commit.get("sha"):
        return ""
    info = _sub_dict(commit, "commit")
    author_info = _sub_dict(info, "author")
    author = _login(commit)
    if author == "ghost":
        author = str(author_info.get("name") or "").strip() or "unknown"
    when = _time_label(author_info.get("date"))
    message = str(info.get("message") or "").strip()
    subject = (message.splitlines() or ["(no commit message)"])[0]

    bullets = [f"Commit: {_escape(str(commit.get('sha') or '')[:12])}"]
    stats = _sub_dict(commit, "stats")
    if stats:
        bullets.append(_escape(
            f"{stats.get('additions', 0)} additions, {stats.get('deletions', 0)} deletions"
        ))
    parents = _sub_list(commit, "parents")
    if parents:
        bullets.append(_escape(
            "Parents: " + ", ".join(str(p.get("sha") or "")[:7] for p in parents if isinstance(p, dict))
        ))
    bullets.append(f"Repository: {_link(f'https://github.com/{target.slug}', target.slug)}")

    heading = f"Commit by {author}"
    if when:
        heading += f" — {when}"
    sections = [_section(1, heading, _bullets(bullets) + _plain_text_html(message))]
    index = 2

    events = _comment_events(
        _api_list(f"{base}/commits/{target.ref}/comments", timeout=timeout, max_items=_MAX_COMMENTS),
        "Comment",
    )
    events.sort(key=_sort_key)
    timeline, index = _timeline_sections(events, index)
    sections.extend(timeline)

    files = _sub_list(commit, "files")
    sections.extend(_files_sections(files[:_MAX_FILES], index, changed_label="Changed files"))
    return _document(f"{subject} ({target.slug})", target.canonical_url, author, sections)


def _release_document(target: GitHubTarget, *, timeout: float) -> str:
    base = f"/repos/{quote(target.owner, safe='')}/{quote(target.repo, safe='')}"
    release = _api_get(f"{base}/releases/tags/{quote(target.ref, safe='')}", timeout=timeout)
    if not isinstance(release, dict) or not release.get("tag_name"):
        return ""
    author = _login(release)
    title = str(release.get("name") or "").strip() or str(release.get("tag_name") or "").strip()
    published = _time_label(release.get("published_at") or release.get("created_at"))
    heading = f"Release published by {author}"
    if published:
        heading += f" — {published}"

    bullets = [f"Tag: {_escape(release.get('tag_name'))}"]
    if release.get("prerelease"):
        bullets.append("Pre-release")
    if release.get("draft"):
        bullets.append("Draft")
    bullets.append(f"Repository: {_link(f'https://github.com/{target.slug}', target.slug)}")
    sections = [_section(1, heading, _bullets(bullets) + _body_html(release))]

    assets = _sub_list(release, "assets")
    rows = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip() or "asset"
        href = str(asset.get("browser_download_url") or "").strip()
        downloads = asset.get("download_count")
        label = name if not isinstance(downloads, int) else f"{name} ({downloads} downloads)"
        rows.append(_link(href, label) if href else _escape(label))
    if rows:
        sections.append(_section(2, f"Assets ({len(rows)})", _bullets(rows)))
    return _document(f"{title} ({target.slug})", target.canonical_url, author, sections)


def _discussion_document(target: GitHubTarget, *, timeout: float) -> str:
    """A discussion (GitHub's forum) — opening post, every comment, every reply.

    Repository discussions come from the REST API, whose comment listing already
    contains the threaded replies (flat, each carrying ``parent_id``). Anything
    it cannot serve — an organization discussion, a rate-limited call — falls
    through to the rendered page, which GitHub does serve server-side.
    """
    if target.kind == "discussion":
        document = _discussion_from_api(target, timeout=timeout)
        if document:
            return document
    return _discussion_from_html(target, timeout=timeout)


def _discussion_from_api(target: GitHubTarget, *, timeout: float) -> str:
    base = f"/repos/{quote(target.owner, safe='')}/{quote(target.repo, safe='')}"
    discussion = _api_get(f"{base}/discussions/{target.ref}", timeout=timeout)
    if not isinstance(discussion, dict) or not discussion.get("number"):
        return ""

    title = str(discussion.get("title") or "").strip() or f"Discussion #{target.ref}"
    author = _login(discussion)
    opened = _time_label(discussion.get("created_at"))
    heading = f"Discussion opened by {author}"
    if opened:
        heading += f" — {opened}"

    bullets = []
    category = _sub_dict(discussion, "category")
    if category.get("name"):
        bullets.append(f"Category: {_escape(category.get('name'))}")
    labels = _name_list(discussion.get("labels"))
    if labels:
        bullets.append(f"Labels: {_escape(labels)}")
    answered = _time_label(discussion.get("answer_chosen_at"))
    if answered:
        chooser = _sub_dict(discussion, "answer_chosen_by").get("login") or ""
        bullets.append(_escape(
            f"Marked answered: {answered}" + (f" by {chooser}" if chooser else "")
        ))
    bullets.append(f"Repository: {_link(f'https://github.com/{target.slug}', target.slug)}")
    sections = [_section(1, heading, _bullets(bullets) + _body_html(discussion))]

    answer_url = str(discussion.get("answer_html_url") or "").strip()
    comments = _api_list(f"{base}/discussions/{target.ref}/comments",
                         timeout=timeout, max_items=_MAX_COMMENTS)
    # Replies arrive in the same listing, so a reply's parent already has its
    # number by the time the reply is rendered.
    numbers = {}
    index = 2
    for comment in comments:
        body = _body_html(comment)
        if not body.strip():
            continue
        identity = comment.get("id")
        numbers[identity] = index
        label = "Comment"
        if answer_url and str(comment.get("html_url") or "").strip() == answer_url:
            label = "Answer"
        heading = f"{label} by {_login(comment)}"
        parent = numbers.get(comment.get("parent_id"))
        if parent:
            heading += f" — reply to #{parent}"
        when = _time_label(comment.get("created_at"))
        if when:
            heading += f" — {when}"
        sections.append(_section(index, heading, body))
        index += 1
    return _document(f"{title} ({target.slug}#{target.ref})", target.canonical_url, author, sections)


def _html_comment_author(group) -> str:
    """The account that wrote one rendered comment (its profile link)."""
    for anchor in group.select("a[href]"):
        href = str(anchor.get("href") or "")
        if re.fullmatch(r"/[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", href):
            name = anchor.get_text(" ", strip=True)
            if name:
                return name
    return "ghost"


def _discussion_from_html(target: GitHubTarget, *, timeout: float) -> str:
    """Rebuild a discussion from its rendered page (organization discussions).

    GitHub renders discussion posts server-side, so the conversation is present
    in the HTML — but as sibling comment blocks that generic extraction reduces
    to one post. Each block becomes an attributed section, and a nested block is
    a threaded reply.
    """
    from bs4 import BeautifulSoup  # local: keeps the API path import-light

    url = target.canonical_url
    try:
        response = utils.safe_requests_get(
            url, timeout=max(1.0, float(timeout or 20)),
            headers={"Accept": "text/html,application/xhtml+xml"}, allow_redirects=True,
        )
    except Exception:
        log.debug("GitHub discussion page fetch failed for %s", url, exc_info=True)
        return ""
    if int(getattr(response, "status_code", 0) or 0) != 200:
        return ""
    try:
        soup = BeautifulSoup(getattr(response, "text", "") or "", "html.parser")
    except Exception:
        return ""

    title = ""
    meta = soup.find("meta", attrs={"property": "og:title"})
    if meta is not None:
        title = str(meta.get("content") or "").strip()
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    # "Some title · community · Discussion #16925" — keep the discussion's own title.
    title = title.split(" · ")[0].strip() or f"Discussion #{target.ref}"

    sections = []
    author = ""
    index = 1
    for group in soup.select("div.timeline-comment-group"):
        body = group.select_one(".comment-body") or group.select_one(".markdown-body")
        if body is None or not body.get_text(strip=True):
            continue
        for junk in body.select("script, style, form, button, input, textarea, svg"):
            junk.decompose()
        for attr in ("class", "id"):
            if body.has_attr(attr):
                del body[attr]
        who = _html_comment_author(group)
        if not author:
            author = who
        when = ""
        for stamp in group.select("relative-time[datetime]"):
            value = str(stamp.get("datetime") or "")
            if value[:1].isdigit():
                when = _time_label(value)
                break
        label = "Discussion opened by" if index == 1 else "Comment by"
        heading = f"{label} {who}"
        if group.find_parent("div", class_="timeline-comment-group") is not None:
            heading += " — reply"
        if when:
            heading += f" — {when}"
        sections.append(_section(index, heading, str(body)))
        index += 1
    if len(sections) < 1:
        return ""
    return _document(f"{title} ({target.slug}#{target.ref})", url, author, sections)


_RENDERERS = {
    "pull": _pull_document,
    "issue": _issue_document,
    "commit": _commit_document,
    "release": _release_document,
    "discussion": _discussion_document,
    "org_discussion": _discussion_document,
}


def download_page_html(url: str, *, timeout: float = 20) -> str:
    """Return one semantic document for a GitHub page, or '' to fall back.

    Covers the whole page the way a sighted reader sees it: description,
    metadata, commit list, every conversation comment and code review in the
    order they were written, then the diff — instead of the diff table alone.
    """
    target = parse_target(url)
    if target is None:
        return ""
    renderer = _RENDERERS.get(target.kind)
    if renderer is None:
        return ""
    try:
        return renderer(target, timeout=timeout)
    except Exception:
        log.debug("GitHub page reconstruction failed for %s", url, exc_info=True)
        return ""
