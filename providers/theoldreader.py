import requests
import time
import urllib.parse
import logging
from typing import List, Dict, Any
from datetime import datetime, timezone
from .base import RSSProvider
from core.models import Feed, Article
from core import utils

log = logging.getLogger(__name__)

class TheOldReaderProvider(RSSProvider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.conf = config.get("providers", {}).get("theoldreader", {})
        self.email = self.conf.get("email", "")
        self.password = self.conf.get("password", "")
        self.token = None
        self.base_url = "https://theoldreader.com/reader/api/0"

    def get_name(self) -> str:
        return "TheOldReader"

    def _timeout_s(self) -> int:
        """Default network timeout for TheOldReader API calls.

        Without an explicit timeout, requests can hang indefinitely and keep the
        refresh guard locked until the app restarts.
        """
        try:
            base = int(self.config.get("feed_timeout_seconds", 15) or 15)
        except Exception:
            base = 15
        return max(5, min(120, int(base)))

    def _login(self):
        if self.token:
            log.debug("TheOldReader: Using existing token.")
            return True
        log.info(f"TheOldReader: Attempting login for {self.email}...")
        try:
            resp = requests.post("https://theoldreader.com/accounts/ClientLogin", data={
                "client": "BlindRSS",
                "accountType": "HOSTED_OR_GOOGLE",
                "service": "reader",
                "Email": self.email,
                "Passwd": self.password,
                "output": "json"
            }, headers=utils.HEADERS, timeout=self._timeout_s())
            
            if resp.status_code != 200:
                log.error(f"TheOldReader: Login Failed! Status: {resp.status_code}, Body: {resp.text[:200]}...")
                return False
                
            for line in resp.text.splitlines():
                if line.startswith("Auth="):
                    self.token = line.split("=", 1)[1]
                    log.info("TheOldReader: Login Success - Token found in text.")
                    return True
            
            try:
                data = resp.json()
                if "Auth" in data:
                    self.token = data["Auth"]
                    log.info("TheOldReader: Login Success - Token found in JSON.")
                    return True
            except: pass # Not JSON
            
            log.error("TheOldReader: Login Failed! No Auth token found in response.")
            return False
        except Exception as e:
            log.exception(f"TheOldReader Login Error: {e}")
            return False

    def _headers(self):
        h = utils.add_revalidation_headers(utils.HEADERS)
        if self.token:
            h["Authorization"] = f"GoogleLogin auth={self.token}"
        return h

    def _strip_view_prefixes(self, feed_id: str) -> str:
        real_feed_id = feed_id or ""
        while True:
            if real_feed_id.startswith("favorites:"):
                real_feed_id = real_feed_id[10:]
            elif real_feed_id.startswith("fav:"):
                real_feed_id = real_feed_id[4:]
            elif real_feed_id.startswith("starred:"):
                real_feed_id = real_feed_id[8:]
            elif real_feed_id.startswith("unread:"):
                real_feed_id = real_feed_id[7:]
            elif real_feed_id.startswith("read:"):
                real_feed_id = real_feed_id[5:]
            else:
                break
        return real_feed_id

    def _resolve_stream_id(self, feed_id: str) -> str | None:
        if not feed_id:
            return None
        if feed_id.startswith(("favorites:", "fav:", "starred:", "read:")):
            return None
        real_feed_id = self._strip_view_prefixes(feed_id)
        if not real_feed_id or real_feed_id == "all":
            return "user/-/state/com.google/reading-list"
        if real_feed_id.startswith("category:"):
            label = real_feed_id.split(":", 1)[1]
            return f"user/-/label/{label}"
        return real_feed_id

    def _resolve_item_feed_id(self, item: Dict[str, Any], fallback_feed_id: str | None) -> str:
        origin = None
        try:
            origin = (item.get("origin") or {}).get("streamId")
        except Exception:
            origin = None
        return str(origin or fallback_feed_id or "")

    def _build_item_cache_id(self, item: Dict[str, Any], fallback_feed_id: str | None) -> str | None:
        article_id = item.get("id")
        if article_id is None:
            return None
        feed_id = self._resolve_item_feed_id(item, fallback_feed_id)
        return utils.build_cache_id(str(article_id), feed_id, self.get_name())

    def _iter_unread_ids(self, stream_id: str):
        if not stream_id:
            return
        continuation = None
        base_params = {
            "s": stream_id,
            "output": "json",
            "n": 1000,
            "xt": "user/-/state/com.google/read",
        }
        while True:
            params = dict(base_params)
            if continuation:
                params["c"] = continuation
            resp = requests.get(
                f"{self.base_url}/stream/items/ids",
                headers=self._headers(),
                params=params,
                timeout=self._timeout_s(),
            )
            resp.raise_for_status()
            data = resp.json() if resp is not None else {}
            items = data.get("items") or []
            for item_id in items:
                if item_id is not None:
                    yield str(item_id)
            continuation = data.get("continuation")
            if not continuation or not items:
                break

    def _set_read_state_batch(self, article_ids: List[str], is_read: bool) -> bool:
        if not self._login():
            return False
        if not article_ids:
            return True
        action_key = "a" if is_read else "r"
        state_value = "user/-/state/com.google/read"
        chunk_size = 200
        ok = True
        for i in range(0, len(article_ids), chunk_size):
            chunk = article_ids[i:i + chunk_size]
            data = [("i", str(aid)) for aid in chunk if aid is not None]
            if not data:
                continue
            data.append((action_key, state_value))
            try:
                resp = requests.post(
                    f"{self.base_url}/edit-tag",
                    headers=self._headers(),
                    data=data,
                    timeout=self._timeout_s(),
                )
                if not resp.ok:
                    ok = False
            except Exception as e:
                log.error(f"TheOldReader batch edit-tag failed: {e}")
                ok = False
        return ok

    def refresh(self, progress_cb=None, force: bool = False) -> bool:
        if not self._login():
            log.warning("TheOldReader: Refresh skipped due to login failure.")
            return False
        return True

    def get_feeds(self) -> List[Feed]:
        if not self._login(): 
            log.warning("TheOldReader: Get Feeds skipped due to login failure.")
            return []
        
        log.info("TheOldReader: Fetching feeds...")
        try:
            resp = requests.get(
                f"{self.base_url}/subscription/list",
                headers=self._headers(),
                params={"output": "json"},
                timeout=self._timeout_s(),
            )
            resp.raise_for_status()
            data = resp.json()
            
            resp_counts = requests.get(
                f"{self.base_url}/unread-count",
                headers=self._headers(),
                params={"output": "json"},
                timeout=self._timeout_s(),
            )
            counts = {}
            if resp_counts.ok:
                for item in resp_counts.json().get("unreadcounts", []):
                    counts[item["id"]] = item["count"]
            
            feeds = []
            for sub in data.get("subscriptions", []):
                feed_id = sub["id"]
                cat = "Uncategorized"
                if sub.get("categories"):
                    cat = sub["categories"][0]["label"]
                
                feeds.append(Feed(
                    id=feed_id,
                    title=sub["title"],
                    url=sub["url"],
                    category=cat,
                    icon_url=sub.get("iconUrl", "")
                ))
                feeds[-1].unread_count = counts.get(feed_id, 0)
            log.info(f"TheOldReader: Found {len(feeds)} feeds.")
            return feeds
        except Exception as e:
            log.exception(f"TheOldReader Feeds Error: {e}")
            return []

    def get_articles(self, feed_id: str) -> List[Article]:
        if not self._login(): 
            log.warning("TheOldReader: Login failed, cannot get articles.")
            return []
        
        try:
            real_feed_id = feed_id
            params = {"output": "json", "n": 50}

            if feed_id.startswith("unread:"):
                real_feed_id = feed_id[7:]
                params["xt"] = "user/-/state/com.google/read"
            elif feed_id.startswith("read:"):
                real_feed_id = feed_id[5:]
                params["it"] = "user/-/state/com.google/read"

            if real_feed_id == "all":
                stream_id = "user/-/state/com.google/reading-list"
            elif real_feed_id.startswith("category:"):
                label = real_feed_id.split(":", 1)[1]
                stream_id = f"user/-/label/{label}"
            elif real_feed_id.startswith("favorites:") or real_feed_id.startswith("starred:"):
                stream_id = "user/-/state/com.google/starred"
            else:
                stream_id = real_feed_id
            
            # Use 's' parameter for stream ID to avoid path encoding issues with TheOldReader
            url = f"{self.base_url}/stream/contents"
            params["s"] = stream_id
            
            log.debug(f"TheOldReader: Fetching articles for {stream_id} -> {url} params={params}")
            resp = requests.get(url, headers=self._headers(), params=params, timeout=self._timeout_s())
            log.debug(f"TheOldReader: Article fetch status: {resp.status_code}. Final URL: {resp.url}")
            resp.raise_for_status()
            data = resp.json()
            
            items = data.get("items", [])
            log.info(f"TheOldReader: Found {len(items)} items in API response.")
            
            article_ids = [item["id"] for item in items]
            chapters_map = utils.get_chapters_batch(article_ids)
            
            articles = []
            fallback_feed_id = real_feed_id or stream_id or feed_id
            for item in items:
                content = ""
                if "summary" in item: content = item["summary"]["content"]
                if "content" in item: content = item["content"]["content"]
                
                media_url = None
                media_type = None
                if "enclosure" in item and item["enclosure"]:
                    encs = item["enclosure"]
                    if isinstance(encs, list) and encs:
                        media_url = encs[0].get("href")
                        media_type = encs[0].get("type")
                
                article_id = item["id"]
                article_feed_id = self._resolve_item_feed_id(item, fallback_feed_id)
                cache_id = self._build_item_cache_id(item, fallback_feed_id)
                article_url = item.get("alternate", [{}])[0].get("href", "")
                display_title = utils.enhance_activity_entry_title(item.get("title", ""), article_url, content) or item.get("title", "No Title")
                pub_timestamp = item.get("published")
                date = "0001-01-01 00:00:00"
                if pub_timestamp:
                    try:
                        dt = datetime.fromtimestamp(int(pub_timestamp), timezone.utc)
                        date = utils.format_datetime(dt)
                        log.debug(f"TheOldReader: Parsed date from {pub_timestamp} to {date}")
                    except Exception as date_e:
                        log.debug(f"TheOldReader: Date parsing error for {pub_timestamp}: {date_e}. Falling back to normalize_date.")
                        date = utils.normalize_date(
                            str(pub_timestamp),
                            display_title,
                            content,
                            article_url
                        )
                else:
                    log.debug("TheOldReader: 'published' field missing. Falling back to normalize_date.")
                    date = utils.normalize_date(
                        "",
                        display_title,
                        content,
                        article_url
                    )
                log.debug(f"TheOldReader: Final article date for '{display_title[:30]}...': {date}")
                
                chapters = chapters_map.get(article_id, [])

                is_fav = False
                is_read_flag = False
                for cat in item.get("categories", []):
                    if "starred" in cat:
                        is_fav = True
                    if "read" in cat and "com.google" in cat:
                        is_read_flag = True

                articles.append(Article(
                    id=article_id,
                    feed_id=article_feed_id,
                    title=display_title,
                    url=article_url,
                    content=content,
                    date=date,
                    author=item.get("author", "Unknown"),
                    is_read=is_read_flag,
                    is_favorite=is_fav,
                    media_url=media_url,
                    media_type=media_type,
                    chapters=chapters,
                    cache_id=cache_id,
                ))
            log.info(f"TheOldReader: Returning {len(articles)} processed articles.")
            return articles
        except requests.exceptions.HTTPError as he:
            log.error(f"TheOldReader Articles HTTP Error: {he.response.status_code} - {he.response.text[:200]}")
            return []
        except Exception as e:
            log.exception(f"TheOldReader Articles General Error: {e}")
            return []

    def get_article_chapters(self, article_id: str) -> List[Dict]:
        return utils.get_chapters_from_db(article_id)

    def mark_read(self, article_id: str) -> bool:
        if not self._login(): return False
        try:
            requests.post(f"{self.base_url}/edit-tag", headers=self._headers(), data={
                "i": article_id,
                "a": "user/-/state/com.google/read"
            }, timeout=self._timeout_s())
            return True
        except:
            return False

    def mark_unread(self, article_id: str) -> bool:
        if not self._login(): return False
        try:
            requests.post(f"{self.base_url}/edit-tag", headers=self._headers(), data={
                "i": article_id,
                "r": "user/-/state/com.google/read"
            }, timeout=self._timeout_s())
            return True
        except:
            return False

    def mark_read_batch(self, article_ids: List[str]) -> bool:
        return self._set_read_state_batch(article_ids, True)

    def mark_all_read(self, feed_id: str) -> bool:
        if not self._login():
            return False
        if not feed_id or feed_id.startswith(("favorites:", "fav:", "starred:", "read:")):
            return False
        stream_id = self._resolve_stream_id(feed_id)
        if not stream_id:
            return False

        try:
            ts = int(time.time() * 1_000_000)
            resp = requests.post(
                f"{self.base_url}/mark-all-as-read",
                headers=self._headers(),
                data={"s": stream_id, "ts": str(ts)},
                timeout=self._timeout_s(),
            )
            if resp.ok:
                return True
        except Exception as e:
            log.error(f"TheOldReader mark-all-as-read failed for {feed_id}: {e}")

        try:
            unread_ids = list(self._iter_unread_ids(stream_id))
            if not unread_ids:
                return True
            return self._set_read_state_batch(unread_ids, True)
        except Exception as e:
            log.error(f"TheOldReader mark-all fallback failed for {feed_id}: {e}")
            return False

    def supports_favorites(self) -> bool:
        return True

    def set_favorite(self, article_id: str, is_favorite: bool) -> bool:
        if not self._login(): return False
        try:
            action = "a" if is_favorite else "r"
            requests.post(f"{self.base_url}/edit-tag", headers=self._headers(), data={
                "i": article_id,
                action: "user/-/state/com.google/starred"
            }, timeout=self._timeout_s())
            return True
        except Exception as e:
            log.error(f"TheOldReader Set Favorite Error: {e}")
            return False

    def toggle_favorite(self, article_id: str):
        if not self._login(): return None
        try:
            # TheOldReader API supports stream/items/ids
            resp = requests.get(
                f"{self.base_url}/stream/items/ids",
                headers=self._headers(),
                params={"i": article_id, "output": "json"},
                timeout=self._timeout_s(),
            )
            if resp.ok:
                items = resp.json().get("items", [])
                if items:
                    cats = items[0].get("categories", [])
                    is_fav = any("starred" in c for c in cats)
                    new_state = not is_fav
                    self.set_favorite(article_id, new_state)
                    return new_state
        except:
            pass
        return None

    def add_feed(self, url: str, category: str = None) -> bool:
        if not self._login(): return False
        from core.discovery import get_ytdlp_feed_url, discover_feed
        real_url = get_ytdlp_feed_url(url) or discover_feed(url) or url
        try:
            requests.post(f"{self.base_url}/subscription/edit", headers=self._headers(), data={
                "s": f"feed/{real_url}",
                "ac": "subscribe",
                "t": category or ""
            }, timeout=self._timeout_s())
            return True
        except:
            return False

    def remove_feed(self, feed_id: str) -> bool:
        if not self._login(): return False
        try:
            requests.post(f"{self.base_url}/subscription/edit", headers=self._headers(), data={
                "s": feed_id,
                "ac": "unsubscribe"
            }, timeout=self._timeout_s())
            return True
        except:
            return False

    def supports_feed_edit(self) -> bool:
        return True

    def supports_feed_url_update(self) -> bool:
        return False

    def update_feed(self, feed_id: str, title: str = None, url: str = None, category: str = None) -> bool:
        if not self._login():
            return False
        data = {"s": feed_id, "ac": "edit"}
        if title is not None:
            data["t"] = title

        # Update category tag when it changes.
        if category is not None:
            current_cat = None
            try:
                for f in self.get_feeds():
                    if f.id == feed_id:
                        current_cat = f.category or "Uncategorized"
                        break
            except Exception:
                current_cat = None
            if current_cat and current_cat != category:
                if current_cat and current_cat != "Uncategorized":
                    data["r"] = f"user/-/label/{current_cat}"
                if category and category != "Uncategorized":
                    data["a"] = f"user/-/label/{category}"

        try:
            resp = requests.post(
                f"{self.base_url}/subscription/edit",
                headers=self._headers(),
                data=data,
                timeout=self._timeout_s(),
            )
            return resp.ok
        except Exception as e:
            log.error(f"TheOldReader Update Feed Error: {e}")
            return False

    def get_categories(self) -> List[str]:
        if not self._login(): return []
        try:
            resp = requests.get(
                f"{self.base_url}/tag/list",
                headers=self._headers(),
                params={"output": "json"},
                timeout=self._timeout_s(),
            )
            resp.raise_for_status()
            data = resp.json()
            cats = []
            for tag in data.get("tags", []):
                tag_id = tag.get("id", "")
                if tag_id.startswith("user/") and "/label/" in tag_id:
                    label = tag_id.split("/label/", 1)[1]
                    cats.append(label)
            return sorted(cats)
        except Exception as e:
            log.exception(f"TheOldReader Get Categories Error: {e}")
            return []

    def add_category(self, title: str) -> bool:
        return True

    def rename_category(self, old_title: str, new_title: str) -> bool:
        if not self._login(): return False
        try:
            source = f"user/-/label/{old_title}"
            dest = f"user/-/label/{new_title}"
            resp = requests.post(f"{self.base_url}/rename-tag", headers=self._headers(), data={
                "s": source,
                "dest": dest
            }, timeout=self._timeout_s())
            return resp.ok
        except Exception as e:
            log.exception(f"TheOldReader Rename Category Error: {e}")
            return False

    def delete_category(self, title: str) -> bool:
        if not self._login(): return False
        try:
            tag = f"user/-/label/{title}"
            requests.post(f"{self.base_url}/disable-tag", headers=self._headers(), data={
                "s": tag
            }, timeout=self._timeout_s())
            return True
        except Exception as e:
            log.exception(f"TheOldReader Delete Category Error: {e}")
            return False
