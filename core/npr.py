# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import re
import json
import logging
from bs4 import BeautifulSoup
from core import utils

log = logging.getLogger(__name__)

def is_npr_url(url: str) -> bool:
    if not url:
        return False
    return "npr.org" in url.lower()

def extract_npr_audio(url: str, timeout_s: float = 10.0) -> tuple[str | None, str | None]:
    """
    Extracts the audio URL and type from an NPR story page.
    Returns (audio_url, audio_type).
    """
    if not is_npr_url(url):
        return None, None
        
    try:
        resp = utils.safe_requests_get(url, timeout=timeout_s)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        
        # 1. Try finding data-audio JSON (New NPR CMS / Brightspot)
        # Often in <div class="audio-module-controls-wrap" data-audio='...'>
        node = soup.find(attrs={"data-audio": True})
        if node:
            try:
                raw_json = node["data-audio"]
                data = json.loads(raw_json)
                audio_url = data.get("audioUrl")
                if audio_url:
                    # Unescape backslashes if any (though json.loads handles standard escapes)
                    # NPR sometimes has double-escaped slashes in raw strings if scraped via regex,
                    # but via soup it should be clean. Just to be safe:
                    if "\\/" in audio_url:
                        audio_url = audio_url.replace("\\/", "/")
                    return audio_url, "audio/mpeg"
            except Exception as e:
                log.debug(f"NPR data-audio JSON parse failed: {e}")

        # 2. Try finding download/listen link
        # <a class="audio-module-listen" href="...">
        link = soup.find("a", class_="audio-module-listen")
        if link and link.get("href"):
            href = link["href"]
            if ".mp3" in href:
                return href, "audio/mpeg"

        # 3. Fallback: Search for any link containing .mp3 from ondemand.npr.org
        # This is a bit looser but helps with older layouts.
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "ondemand.npr.org" in href and ".mp3" in href:
                return href, "audio/mpeg"

    except Exception as e:
        log.warning(f"NPR audio extraction failed for {url}: {e}")
        
    return None, None
