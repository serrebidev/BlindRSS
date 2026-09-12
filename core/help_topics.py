# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Registry of user-guide topics and the UI-to-topic maps behind F1.

The user guide itself lives in ``docs/help/<lang>.md`` (see ``core.help_docs``);
this module is the *index*: the canonical list of section anchors plus the
tables that answer "which section documents the thing the user is looking at?".

It is deliberately GUI-free so both halves stay unit-testable without wx:

    TOPICS                   ordered (id, English title) of every guide section
    COMMAND_TOPICS           core.shortcuts command id  -> topic id
    DIALOG_TOPICS            wx window/dialog class name -> topic id
    NOTEBOOK_PAGE_TOPICS     (dialog class, English tab title) -> topic id
    MENU_TITLE_TOPICS        English menu-bar title      -> topic id
    CONTEXT_MENU_TOPICS      English context-menu label  -> topic id

``tests/test_help_system.py`` asserts that every id used on the right-hand side
of those tables really is a section in ``docs/help/en.md``, and that every
command in ``core.shortcuts.COMMANDS`` has a mapping — so a new command or a
renamed section cannot silently degrade F1 to the generic fallback.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

# Topic shown when nothing more specific is known. Always present in the guide.
DEFAULT_TOPIC = "user-guide"


def _(text):  # noqa: A001 - gettext-noop marker for tools/extract_strings.py
    """Identity gettext marker (see core.shortcuts for the same pattern).

    Topic titles are English msgids here and translated at display time, which
    the AST-based POT extractor cannot follow. Routing them through this no-op
    ``_`` records them in ``locale/blindrss.pot``.
    """
    return text


# --------------------------------------------------------------------------
# The guide's sections, in document order.
# --------------------------------------------------------------------------
#
# NOTE: keep ids stable. They are the anchors written into docs/help/*.md as
# "## Title {#id}" and every translated guide reuses them verbatim, so renaming
# one silently orphans that section in every language.
TOPICS: List[Tuple[str, str]] = [
    ("user-guide", _("BlindRSS User Guide")),
    ("getting-started", _("Getting Started")),
    ("main-window", _("The Main Window")),
    ("feed-tree", _("Feeds and Folders List")),
    ("article-list", _("Article List")),
    ("reading-pane", _("Reading Pane")),
    ("article-window", _("Article Window")),
    ("search-field", _("Search Field")),
    ("status-bar", _("Status Bar")),
    ("context-menus", _("Context Menus")),

    ("adding-feeds", _("Adding a Feed")),
    ("detect-feeds", _("Detecting Feeds on a Page")),
    ("find-podcast", _("Finding Podcasts and RSS Feeds")),
    ("podcast-directories", _("Podcast and Feed Directories")),
    ("subscribing", _("Subscribing to a Search Result")),
    ("podcast-archive", _("Podcast Archive")),
    ("video-search", _("Video Search")),
    ("open-article-url", _("Opening an Article by URL")),
    ("open-media-url", _("Opening a Media URL")),
    ("removing-feeds", _("Removing a Feed")),
    ("feed-properties", _("Feed Properties")),
    ("categories", _("Categories and Subcategories")),
    ("category-properties", _("Category Properties")),
    ("refreshing", _("Refreshing Feeds")),
    ("feed-errors", _("Feeds with Errors")),

    ("import-opml", _("Importing OPML")),
    ("export-opml", _("Exporting OPML")),
    ("import-youtube-takeout", _("Importing a YouTube Takeout Archive")),

    ("persistent-search", _("Persistent Searches")),
    ("smart-folders", _("Smart Folders")),
    ("filter-rules", _("Filter Rules")),
    ("article-filter", _("Article Filter")),
    ("sorting", _("Sorting Articles")),
    ("list-headers", _("Article List Columns")),

    ("opening-articles", _("Opening Articles")),
    ("read-status", _("Read and Unread Articles")),
    ("favorites", _("Favorites")),
    ("deleted-articles", _("Deleted Articles")),
    ("full-text", _("Full-Text Article Recovery")),
    ("rich-view", _("Rich Full-Text View")),
    ("accessible-browser", _("Accessible Browser")),
    ("youtube", _("YouTube Videos")),
    ("forums", _("Forum and Discussion Threads")),
    ("clipboard", _("Cut, Copy, and Paste")),

    ("player", _("The Built-in Player")),
    ("player-controls", _("Player Controls")),
    ("player-shortcuts", _("Player Keyboard Shortcuts")),
    ("playback-speed", _("Playback Speed")),
    ("equalizer", _("Equalizer")),
    ("chapters", _("Chapters")),
    ("play-queue", _("Play Queue")),
    ("casting", _("Casting to Other Devices")),
    ("silence-skipping", _("Skip Silence")),
    ("downloads", _("Downloading Media")),

    ("settings", _("Settings")),
    ("settings-general", _("Settings: General")),
    ("settings-feeds", _("Settings: Feeds and Articles")),
    ("settings-youtube", _("Settings: YouTube")),
    ("settings-media-player", _("Settings: Media Player")),
    ("settings-provider", _("Settings: Provider")),
    ("settings-notifications", _("Settings: Notifications")),
    ("settings-translate", _("Settings: Translate")),
    ("settings-list-headers", _("Settings: List Headers")),
    ("settings-advanced", _("Settings: Advanced")),
    ("settings-captcha", _("Settings: CAPTCHA Solving")),

    ("providers", _("Online Accounts and Providers")),
    ("notifications", _("Notifications")),
    ("translation", _("Article Translation")),
    ("site-cookies", _("Importing Site Cookies")),
    ("keyboard-shortcuts", _("Keyboard Shortcuts")),
    ("shortcuts-reference", _("Default Keyboard Shortcuts")),
    ("language", _("Interface Language")),
    ("tray", _("Tray Icon and Media Keys")),
    ("desktop-shortcuts", _("Adding Desktop Shortcuts")),
    ("updates", _("Checking for Updates")),
    ("version", _("Announcing the Version")),
    ("about", _("About BlindRSS")),
    ("help-window", _("Using This Help Window")),
    ("troubleshooting", _("Troubleshooting")),
    ("support", _("Support and Community")),
]

_TOPIC_TITLES: "OrderedDict[str, str]" = OrderedDict(TOPICS)


def topic_ids() -> List[str]:
    """Every known topic id, in guide order."""
    return list(_TOPIC_TITLES.keys())


def is_known_topic(topic_id) -> bool:
    return str(topic_id or "") in _TOPIC_TITLES


def topic_title(topic_id) -> str:
    """English title msgid for ``topic_id`` ("" when unknown)."""
    return _TOPIC_TITLES.get(str(topic_id or ""), "")


def normalize(topic_id) -> str:
    """``topic_id`` if it names a real section, else DEFAULT_TOPIC."""
    candidate = str(topic_id or "").strip()
    return candidate if candidate in _TOPIC_TITLES else DEFAULT_TOPIC


# --------------------------------------------------------------------------
# core.shortcuts command id -> topic
# --------------------------------------------------------------------------
COMMAND_TOPICS: Dict[str, str] = {
    "feeds.add": "adding-feeds",
    "feeds.detect_page": "detect-feeds",
    "feeds.remove": "removing-feeds",
    "feeds.refresh_all": "refreshing",
    "feeds.stop_refresh": "refreshing",
    "feeds.refresh_selected": "refreshing",
    "feeds.edit_selected": "feed-properties",
    "feeds.mark_all_read": "read-status",
    "feeds.view_errors": "feed-errors",
    "feeds.copy_url": "clipboard",
    "feeds.add_category": "categories",
    "feeds.remove_category": "categories",
    "feeds.import_opml": "import-opml",
    "feeds.import_youtube_takeout": "import-youtube-takeout",
    "feeds.export_opml": "export-opml",
    "feeds.find_podcast": "find-podcast",
    "feeds.podcast_archive": "podcast-archive",
    "feeds.video_search": "video-search",

    "media.open_url": "open-media-url",

    "article.open_url": "open-article-url",
    "article.open_browser": "opening-articles",
    "article.copy_link": "clipboard",
    "article.copy_media_link": "clipboard",
    "article.copy_text": "clipboard",
    "article.toggle_read": "read-status",
    "article.toggle_favorite": "favorites",
    "article.delete": "deleted-articles",
    "article.download": "downloads",
    "article.download_as": "downloads",
    "article.toggle_queue": "play-queue",
    "article.view_description": "feed-properties",

    "view.focus_search": "search-field",
    "view.toggle_search": "search-field",
    "view.rich_view": "rich-view",
    "view.accessible_browser": "accessible-browser",

    "filter.read_all": "article-filter",
    "filter.read_unread": "article-filter",
    "filter.read_read": "article-filter",
    "filter.media_all": "article-filter",
    "filter.media_with": "article-filter",
    "filter.media_without": "article-filter",

    "sort.date": "sorting",
    "sort.name": "sorting",
    "sort.author": "sorting",
    "sort.description": "sorting",
    "sort.feed": "sorting",
    "sort.status": "sorting",
    "sort.ascending": "sorting",

    "player.play_pause": "player-controls",
    "player.stop": "player-controls",
    "player.show_hide": "player",
    "player.equalizer": "equalizer",
    "player.chapters": "chapters",

    "queue.open": "play-queue",
    "queue.next": "play-queue",
    "queue.prev": "play-queue",

    "speed.up": "playback-speed",
    "speed.down": "playback-speed",
    "speed.reset": "playback-speed",

    "tools.filter_rules": "filter-rules",
    "tools.import_site_cookies": "site-cookies",
    "tools.persistent_search": "persistent-search",
    "tools.keyboard_shortcuts": "keyboard-shortcuts",
    "tools.settings": "settings",
    "tools.check_updates": "updates",
    "tools.announce_version": "version",

    "help.user_guide": "user-guide",
}


def topic_for_command(command_id, default: Optional[str] = None) -> str:
    """Topic documenting the shortcut command ``command_id``."""
    return COMMAND_TOPICS.get(str(command_id or ""), default or DEFAULT_TOPIC)


# --------------------------------------------------------------------------
# Window / dialog class name -> topic
# --------------------------------------------------------------------------
#
# Keyed by class name rather than the class object so this module never imports
# wx. The resolver walks a focused window's MRO, so a subclass inherits its
# base class's topic for free.
DIALOG_TOPICS: Dict[str, str] = {
    "MainFrame": "main-window",

    "AddFeedDialog": "adding-feeds",
    "OpenMediaUrlDialog": "open-media-url",
    "OpenArticleDialog": "open-article-url",
    "AddShortcutsDialog": "desktop-shortcuts",
    "TakeoutImportSelectionDialog": "import-youtube-takeout",
    "ExcludeNotificationFeedsDialog": "notifications",
    "ImportSiteCookiesDialog": "site-cookies",
    "SettingsDialog": "settings",
    "FeedPropertiesDialog": "feed-properties",
    "CategoryPropertiesDialog": "category-properties",
    "FeedErrorsDialog": "feed-errors",
    "PodcastArchiveDialog": "podcast-archive",
    "FeedSearchDialog": "find-podcast",
    "YtdlpGlobalSearchDialog": "video-search",
    "PersistentSearchDialog": "persistent-search",
    "AboutDialog": "about",
    "QueueDialog": "play-queue",
    "ShortcutCaptureDialog": "keyboard-shortcuts",
    "KeyboardShortcutsDialog": "keyboard-shortcuts",
    "EqualizerDialog": "equalizer",
    "ColumnLayoutPanel": "list-headers",

    "SmartFolderDialog": "smart-folders",
    "FilterRuleEditorDialog": "filter-rules",
    "FilterRulesDialog": "filter-rules",

    "CastDialog": "casting",
    "PlayerFrame": "player",

    "AccessibleBrowserFrame": "accessible-browser",
    "ArticleWindow": "article-window",

    "HelpWindow": "help-window",
}


def topic_for_class_names(names, default: Optional[str] = None) -> Optional[str]:
    """First mapped topic among ``names`` (a class MRO, most derived first)."""
    for name in names or ():
        topic = DIALOG_TOPICS.get(str(name))
        if topic:
            return topic
    return default


# --------------------------------------------------------------------------
# Notebook pages: (dialog class, English tab title) -> topic
# --------------------------------------------------------------------------
#
# Tab titles are the English msgids passed to AddPage. "&&" is wx's escape for
# a literal ampersand and is kept verbatim so the keys match the source.
NOTEBOOK_PAGE_TOPICS: Dict[Tuple[str, str], str] = {
    ("SettingsDialog", "General"): "settings-general",
    ("SettingsDialog", "Feeds && Articles"): "settings-feeds",
    ("SettingsDialog", "YouTube"): "settings-youtube",
    ("SettingsDialog", "Media Player"): "settings-media-player",
    ("SettingsDialog", "Provider"): "settings-provider",
    ("SettingsDialog", "Notifications"): "settings-notifications",
    ("SettingsDialog", "Translate"): "settings-translate",
    ("SettingsDialog", "List Headers"): "settings-list-headers",
    ("SettingsDialog", "Advanced"): "settings-advanced",
    ("SettingsDialog", "CAPTCHA Solving"): "settings-captcha",

    ("FeedPropertiesDialog", "General"): "feed-properties",
    ("FeedPropertiesDialog", "List Headers"): "list-headers",
}


def topic_for_notebook_page(dialog_class, page_title, default: Optional[str] = None) -> Optional[str]:
    return NOTEBOOK_PAGE_TOPICS.get((str(dialog_class or ""), str(page_title or "")), default)


# --------------------------------------------------------------------------
# Menu-bar titles -> topic (F1 on a menu with no item highlighted)
# --------------------------------------------------------------------------
MENU_TITLE_TOPICS: Dict[str, str] = {
    "&File": "feed-tree",
    "&Edit": "clipboard",
    "&View": "main-window",
    "&Player": "player",
    "&Tools": "settings",
    "&Help": "help-window",
}


# --------------------------------------------------------------------------
# Context-menu items -> topic
# --------------------------------------------------------------------------
#
# The feed-tree and article-list context menus are rebuilt on every right-click
# from plain wx.Menu.Append calls, so they are mapped by their English label.
# gui.help_context registers the ids at build time; these keys are what the
# mainframe passes in.
CONTEXT_MENU_TOPICS: Dict[str, str] = {
    # Feed tree
    "Refresh Category": "refreshing",
    "Refresh Feed": "refreshing",
    "Mark All Items as Read": "read-status",
    "Add Subcategory": "categories",
    "Edit Category": "category-properties",
    "Edit Feed...": "feed-properties",
    "Remove Category": "categories",
    "Delete Category and Feeds": "categories",
    "Import OPML Here...": "import-opml",
    "Export Category to OPML...": "export-opml",
    "Reset Title to Feed Default": "feed-properties",
    "Copy Feed URL": "clipboard",
    "Notifications for This Feed": "notifications",
    "Image Alt Text": "reading-pane",
    "Use default setting": "reading-pane",
    "Always show image alt text": "reading-pane",
    "Never show image alt text": "reading-pane",
    "Remove Feed": "removing-feeds",
    "New Smart Folder...": "smart-folders",
    "Edit Smart Folder...": "smart-folders",
    "Delete Smart Folder": "smart-folders",

    # Article list. Labels with a "{count}" placeholder are matched on the
    # fixed text either side of it (gui.help_context), which is how the
    # multi-selection variants resolve.
    "Open Article": "opening-articles",
    "Open in Default Browser": "opening-articles",
    "Mark as &Read": "read-status",
    "Mark as &Unread": "read-status",
    "Mark {count} as &Read": "read-status",
    "Mark {count} as &Unread": "read-status",
    "Delete Article": "deleted-articles",
    "Delete {count} Articles": "deleted-articles",
    "Delete Article Permanently": "deleted-articles",
    "Delete {count} Articles Permanently": "deleted-articles",
    "Restore Article": "deleted-articles",
    "Restore {count} Articles": "deleted-articles",
    "Copy Link": "clipboard",
    "Copy Links": "clipboard",
    "Copy Text": "clipboard",
    "Copy Text ({count} articles)": "clipboard",
    "Copy Media Link": "clipboard",
    "Copy Image Link": "clipboard",
    "View Feed Description...": "feed-properties",
    "Detect Audio": "player",
    "Download": "downloads",
    "Download As...": "downloads",
    "Add to Favorites": "favorites",
    "Remove from Favorites": "favorites",
    "Add to Play Queue": "play-queue",
    "Remove from Play Queue": "play-queue",
    "Add {count} to Play Queue": "play-queue",
    "Remove {count} from Play Queue": "play-queue",
    "Open Play Queue...": "play-queue",
    "Chapter Links": "chapters",
    "View History...": "podcast-archive",
}


