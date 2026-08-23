# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Shared podcast-history sidecar for hosted RSS providers.

Google Reader-style services can read and mutate their own entries but do not
offer an API for BlindRSS to insert episodes reconstructed from Wayback.  This
mixin discovers those episodes in the background, stores them in the local
provider/account-scoped sidecar, and merges them into direct feed views.
"""

import hashlib
import logging
import threading
import time

from core import db, podcast_archive, utils
from core.models import Article


log = logging.getLogger(__name__)


class HostedPodcastArchiveMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._podcast_archive_queued_ids: set[str] = set()
        self._podcast_archive_queued_lock = threading.Lock()
        self._podcast_feed_urls: dict[str, str] = {}

    def _podcast_archive_account_identity(self) -> str:
        """Stable, non-persisted account identity used to scope local rows."""
        return self.get_name()

    def _podcast_archive_scope(self) -> str:
        identity = f"{self.get_name()}|{self._podcast_archive_account_identity()}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        return f"{self.get_name().casefold()}:{digest}"

    @staticmethod
    def podcast_source_url(feed_id: str, advertised_url: str = "") -> str:
        """Prefer the source encoded by Google Reader's `feed/<url>` ID."""
        fid = str(feed_id or "").strip()
        if fid.startswith("feed/"):
            encoded = fid[5:].strip()
            if encoded.lower().startswith(("http://", "https://")):
                return encoded
        return str(advertised_url or "").strip()

    @staticmethod
    def _podcast_archive_result_error(result) -> str:
        if result.snapshots_loaded == 0:
            if result.warnings:
                return str(result.warnings[0])
            if result.snapshots_found > 0:
                return "The Wayback Machine snapshots could not be loaded."
        return ""

    @staticmethod
    def _podcast_archive_episode_key(episode) -> str:
        keys = sorted(episode.identity_keys or podcast_archive._episode_identity_keys(episode))
        identity = "\n".join(keys) or "|".join(
            (
                str(episode.guid or ""), str(episode.media_url or ""),
                str(episode.page_url or ""), str(episode.title or ""),
                str(episode.published or ""),
            )
        )
        return hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()

    def _run_podcast_archive_scan(self, feed_id: str, feed_url: str) -> bool:
        scope = self._podcast_archive_scope()
        fid = str(feed_id or "")
        try:
            public_feed_url = podcast_archive._public_http_url(feed_url)
            try:
                read_timeout = max(5, int(self.config.get("feed_timeout_seconds", 15) or 15))
            except (TypeError, ValueError):
                read_timeout = 15
            connect_timeout = max(1, int(getattr(self, "CONNECT_TIMEOUT_SECONDS", 3) or 3))
            response = utils.safe_requests_get(
                public_feed_url,
                timeout=(connect_timeout, read_timeout),
                site_cookies=False,
            )
            response.raise_for_status()
            current_document = bytes(getattr(response, "content", b"") or b"")
            _title, current_episodes, _lineage = podcast_archive.parse_feed_document(
                current_document,
                str(getattr(response, "url", "") or public_feed_url),
            )
            if not any(episode.media_url for episode in current_episodes):
                db.replace_hosted_podcast_archive_entries(scope, fid, [])
                db.finish_hosted_podcast_archive_scan(scope, fid)
                return True

            try:
                max_snapshots = int(
                    self.config.get(
                        "podcast_archive_max_snapshots",
                        podcast_archive.DEFAULT_MAX_SNAPSHOTS,
                    )
                    or podcast_archive.DEFAULT_MAX_SNAPSHOTS
                )
            except (TypeError, ValueError):
                max_snapshots = podcast_archive.DEFAULT_MAX_SNAPSHOTS

            with podcast_archive.AUTOMATIC_SCAN_LOCK:
                result = podcast_archive.scan_podcast_archive(
                    public_feed_url,
                    current_document=current_document,
                    max_snapshots=max_snapshots,
                    include_without_media=True,
                )
            if result.canceled:
                db.reset_hosted_podcast_archive_scan(scope, fid)
                return False
            result_error = self._podcast_archive_result_error(result)
            if result_error:
                db.finish_hosted_podcast_archive_scan(scope, fid, error=result_error)
                return False

            rows = [
                {
                    "episode_key": self._podcast_archive_episode_key(episode),
                    "title": episode.title,
                    "url": episode.page_url,
                    "content": episode.description,
                    "date": episode.published,
                    "author": episode.author,
                    "media_url": episode.media_url,
                    "media_type": episode.media_type,
                }
                for episode in podcast_archive.archive_only_episodes(result, current_document)
                if episode.media_url
            ]
            db.replace_hosted_podcast_archive_entries(scope, fid, rows)
            db.finish_hosted_podcast_archive_scan(
                scope,
                fid,
                snapshot_count=result.snapshots_loaded,
                episode_count=len(result.episodes),
            )
            return True
        except Exception as exc:
            log.warning(
                "%s podcast archive recovery failed for %s: %s",
                self.get_name(), feed_url, exc,
            )
            try:
                db.finish_hosted_podcast_archive_scan(scope, fid, error=str(exc))
            except Exception:
                log.debug("Could not persist hosted podcast archive failure", exc_info=True)
            return False

    def _queue_podcast_archive_scans(self, feeds) -> None:
        if not bool(self.config.get("podcast_archive_enabled", False)):
            return
        try:
            rescan_seconds = max(
                86400.0,
                float(self.config.get("podcast_archive_rescan_days", 30) or 30) * 86400,
            )
        except (TypeError, ValueError):
            rescan_seconds = 30 * 86400
        scope = self._podcast_archive_scope()
        states = db.get_hosted_podcast_archive_states(scope)
        for feed in feeds or []:
            if isinstance(feed, dict):
                fid = str(feed.get("id") or "").strip()
                advertised_url = str(
                    feed.get("source_url") or feed.get("feed_url") or feed.get("url") or ""
                ).strip()
            else:
                fid = str(getattr(feed, "id", "") or "").strip()
                advertised_url = str(
                    getattr(feed, "source_url", "") or getattr(feed, "url", "") or ""
                ).strip()
            feed_url = self.podcast_source_url(fid, advertised_url)
            if not fid or not feed_url:
                continue
            self._podcast_feed_urls[fid] = feed_url
            state = states.get(fid) or {"status": "never"}
            now = time.time()
            last_success = state.get("last_success")
            last_attempt = state.get("last_attempt")
            if last_success is not None and now - float(last_success) < rescan_seconds:
                continue
            if state.get("status") == "scanning" and last_attempt is not None and now - float(last_attempt) < 6 * 3600:
                continue
            if state.get("status") == "error" and last_attempt is not None and now - float(last_attempt) < min(rescan_seconds, 86400.0):
                continue
            with self._podcast_archive_queued_lock:
                if fid in self._podcast_archive_queued_ids:
                    continue
                self._podcast_archive_queued_ids.add(fid)

            def job(archive_feed_id=fid, archive_feed_url=feed_url):
                try:
                    if db.claim_hosted_podcast_archive_scan(
                        scope,
                        archive_feed_id,
                        archive_feed_url,
                        rescan_seconds=rescan_seconds,
                    ):
                        self._run_podcast_archive_scan(archive_feed_id, archive_feed_url)
                finally:
                    with self._podcast_archive_queued_lock:
                        self._podcast_archive_queued_ids.discard(archive_feed_id)

            podcast_archive.enqueue_archive_job(job)

    def get_podcast_archive_state(self, feed_id: str) -> dict:
        return db.get_hosted_podcast_archive_state(
            self._podcast_archive_scope(), str(feed_id or "")
        )

    def refresh_podcast_archive(self, feed_id: str, progress_cb=None) -> bool:
        fid = str(feed_id or "").strip()
        feed_url = self._podcast_feed_urls.get(fid, "")
        if not fid or not feed_url:
            # get_feeds refreshes the source map without assuming a provider API.
            self.get_feeds()
            feed_url = self._podcast_feed_urls.get(fid, "")
        if not feed_url:
            return False
        scope = self._podcast_archive_scope()
        db.reset_hosted_podcast_archive_scan(scope, fid)
        if not db.claim_hosted_podcast_archive_scan(scope, fid, feed_url, force=True):
            return False
        return self._run_podcast_archive_scan(fid, feed_url)

    @staticmethod
    def _podcast_article_identity_keys(article: Article) -> set[str]:
        episode = podcast_archive.ArchiveEpisode(
            title=str(article.title or ""),
            page_url=str(article.url or ""),
            media_url=str(article.media_url or ""),
            media_type=str(article.media_type or ""),
            published=str(article.date or ""),
        )
        return podcast_archive._episode_identity_keys(episode)

    def _hosted_archive_articles(self, feed_id: str) -> list[Article]:
        fid = str(feed_id or "")
        rows = db.get_hosted_podcast_archive_entries(self._podcast_archive_scope(), fid)
        articles = []
        for row in rows:
            episode_key = str(row.get("episode_key") or "")
            articles.append(Article(
                id=f"podcast-archive:{episode_key}",
                feed_id=fid,
                title=str(row.get("title") or "Untitled episode"),
                url=str(row.get("url") or ""),
                content=str(row.get("content") or ""),
                description=str(row.get("content") or "") or None,
                date=str(row.get("date") or ""),
                author=str(row.get("author") or ""),
                is_read=True,
                media_url=str(row.get("media_url") or ""),
                media_type=str(row.get("media_type") or ""),
                cache_id=utils.build_cache_id(
                    f"podcast-archive:{episode_key}", fid, self.get_name()
                ),
            ))
        return articles

    @staticmethod
    def _podcast_archive_real_feed_id(feed_id: str) -> str:
        real_feed_id = str(feed_id or "")
        while real_feed_id.startswith(("favorites:", "fav:", "starred:", "unread:", "read:")):
            real_feed_id = real_feed_id.split(":", 1)[1]
        return real_feed_id

    def _merge_hosted_archive_articles(self, feed_id: str, articles) -> list[Article]:
        view_id = str(feed_id or "")
        if view_id.startswith(("unread:", "favorites:", "fav:", "starred:")):
            return list(articles or [])
        fid = self._podcast_archive_real_feed_id(view_id)
        if not fid or fid == "all" or fid.startswith("category:"):
            return list(articles or [])
        merged = list(articles or [])
        live_keys = set()
        for article in merged:
            live_keys.update(self._podcast_article_identity_keys(article))
        for article in self._hosted_archive_articles(fid):
            keys = self._podcast_article_identity_keys(article)
            if keys & live_keys:
                continue
            merged.append(article)
            live_keys.update(keys)
        merged.sort(
            key=lambda article: (
                float(getattr(article, "timestamp", 0.0) or 0.0),
                str(article.title or "").casefold(),
            ),
            reverse=True,
        )
        return merged

    def _has_hosted_archive_entries(self, feed_id: str) -> bool:
        view_id = str(feed_id or "")
        if view_id.startswith(("unread:", "favorites:", "fav:", "starred:")):
            return False
        fid = self._podcast_archive_real_feed_id(view_id)
        if not fid or fid == "all" or fid.startswith("category:"):
            return False
        return bool(db.get_hosted_podcast_archive_entries(self._podcast_archive_scope(), fid))

    @staticmethod
    def is_podcast_archive_article_id(article_id: str) -> bool:
        return str(article_id or "").startswith("podcast-archive:")
