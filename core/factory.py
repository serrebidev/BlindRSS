# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from typing import Dict, Any
from core.db import init_db
from providers.base import RSSProvider
from providers.local import LocalProvider
from providers.miniflux import MinifluxProvider
from providers.theoldreader import TheOldReaderProvider
from providers.inoreader import InoreaderProvider
from providers.bazqux import BazQuxProvider
from providers.youtube_account import YouTubeAccountProvider


def get_provider(config: Dict[str, Any]) -> RSSProvider:
    init_db()

    provider_name = config.get("active_provider", "local")
    
    if provider_name == "miniflux":
        provider = MinifluxProvider(config)
    elif provider_name == "theoldreader":
        provider = TheOldReaderProvider(config)
    elif provider_name == "inoreader":
        provider = InoreaderProvider(config)
    elif provider_name == "bazqux":
        provider = BazQuxProvider(config)
    else:
        # Default to local
        provider = LocalProvider(config)
    return YouTubeAccountProvider(provider, config)
