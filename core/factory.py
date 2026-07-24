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


def get_provider(config: Dict[str, Any]) -> RSSProvider:
    init_db()

    provider_name = config.get("active_provider", "local")
    
    if provider_name == "miniflux":
        return MinifluxProvider(config)
    elif provider_name == "theoldreader":
        return TheOldReaderProvider(config)
    elif provider_name == "inoreader":
        return InoreaderProvider(config)
    elif provider_name == "bazqux":
        return BazQuxProvider(config)
    else:
        # Default to local
        return LocalProvider(config)
