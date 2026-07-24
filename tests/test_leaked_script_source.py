# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Leaked <script>/<style> source must never reach the reader as article text.

Some CMSes build the JSON-LD ``articleBody`` by running a naive tag-stripper over the rendered
article HTML: it deletes the <script> ELEMENT but keeps its JavaScript as "text", and leaves
HTML entities encoded. Every mashable.com story carrying a Reddit/Twitter embed ended with its
lazy-loader being read aloud, and shell commands in the prose spoke "&amp;&amp;" for "&&".
"""

import json
import os
import sys
import unittest

sys.path.append(os.getcwd())
from core import article_extractor


# Verbatim shape of the embed lazy-loader mashable.com leaks into articleBody.
LEAKED_EMBED_SCRIPT = """
        let cbeScripts = {"redditEmbed":["https:\\/\\/embed.reddit.com\\/widgets.js"]};
        let cbeScriptObserver = function (nodeType, scriptsArr) {
            let firstElem = document.querySelector('.' + nodeType)
            let self = this

            if (firstElem == null) {
                console.warn(`CBE cannot find element for script observer.`)
                return;
            }

            scriptsArr.forEach((scriptSrc) => {
                const linkEl = document.createElement('link')
                linkEl.rel = 'dns-prefetch'
                document.head.append(linkEl)
            })

            window[nodeType + 'Loaded'] = false

            this.embedObserver = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    window[nodeType + 'Loaded'] = true
                    self.embedObserver.disconnect()
                })
            }, {root: null, rootMargin: '750px'})
            this.embedObserver.observe(firstElem)
        }

        for (const item in cbeScripts) {
            new cbeScriptObserver(item, cbeScripts[item])
        }
"""

PROSE = (
    "Apple has quietly hidden a new Siri interface in the latest macOS beta, and testers "
    "have already found their way into it."
)


def _page_with_json_ld(article_body: str) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": "A secret Siri interface",
        "articleBody": article_body,
    }
    # Real pages escape "</" as "<\/" inside a <script> block; an unescaped "</script>" in the
    # JSON payload would close the element early and the page would parse as empty.
    blob = json.dumps(payload).replace("</", "<\\/")
    return (
        "<html><head>"
        '<script type="application/ld+json">' + blob + "</script>"
        "</head><body><article><p>Short DOM copy.</p></article></body></html>"
    )


class TestLeakedScriptSource(unittest.TestCase):
    def test_json_ld_body_drops_leaked_script_source(self):
        html = _page_with_json_ld(PROSE + LEAKED_EMBED_SCRIPT)
        text = article_extractor._extract_json_ld_text(html)
        self.assertIn("hidden a new Siri interface", text)
        for marker in ("cbeScripts", "document.querySelector", "IntersectionObserver",
                       "console.warn", "=> {"):
            self.assertNotIn(marker, text, f"leaked JS marker {marker!r} survived")

    def test_json_ld_body_unescapes_entities_when_no_markup_remains(self):
        # The tag-stripper leaves a plain-text body, so the markup branch never runs -- entities
        # must still be decoded or a shell command reads out as "&amp;&amp;".
        body = (
            PROSE
            + " Run: sudo mkdir -p /Library/Preferences &amp;&amp; sudo defaults write x"
            + " &ndash; then reboot."
        )
        text = article_extractor._extract_json_ld_text(_page_with_json_ld(body))
        self.assertIn("/Library/Preferences && sudo defaults write", text)
        self.assertIn("– then reboot", text)
        self.assertNotIn("&amp;", text)
        self.assertNotIn("&ndash;", text)

    def test_real_script_elements_in_body_are_dropped(self):
        body = f"<p>{PROSE}</p><script>{LEAKED_EMBED_SCRIPT}</script><p>Closing line.</p>"
        text = article_extractor._extract_json_ld_text(_page_with_json_ld(body))
        self.assertIn("Closing line.", text)
        self.assertNotIn("cbeScripts", text)

    def test_postprocess_strips_leaked_script_from_any_source(self):
        text = article_extractor._postprocess_extracted_text(
            PROSE + "\n" + LEAKED_EMBED_SCRIPT, "https://example.com/story"
        )
        self.assertIn("hidden a new Siri interface", text)
        self.assertNotIn("cbeScripts", text)
        self.assertNotIn("document.createElement", text)

    def test_shell_snippets_in_prose_survive(self):
        # The very article that exposed this bug prints two `sudo` commands as content. A code
        # stripper that eats those is worse than the bug it fixes.
        body = (
            PROSE
            + "\nsudo mkdir -p /Library/Preferences/FeatureFlags/Domain && sudo defaults write"
            " /Library/Preferences/FeatureFlags/Domain/WritingTools -dict Enabled -bool true"
            "\nAfter that, restart your computer."
            "\nsudo defaults write /Library/Preferences/FeatureFlags/Domain/WritingTools"
            " -dict Enabled -bool false"
        )
        self.assertEqual(article_extractor._strip_embedded_script_code(body), body)

    def test_prose_only_text_is_untouched(self):
        body = (
            "The report notes that Example.com (formerly Sample) shut down.\n"
            "Analysts said the function of the market has changed.\n"
            "Returns, if any, will be issued next week."
        )
        self.assertEqual(article_extractor._strip_embedded_script_code(body), body)

    def test_short_code_sample_is_kept(self):
        # A one-off snippet in a tutorial does not clear the run thresholds.
        body = (
            "To find the element, call the following:\n"
            "document.querySelector('.headline')\n"
            "That returns the first match."
        )
        self.assertEqual(article_extractor._strip_embedded_script_code(body), body)


class TestRecirculationLabels(unittest.TestCase):
    def test_dangling_labels_removed_mid_body(self):
        text = article_extractor._postprocess_extracted_text(
            "First paragraph of the story.\n"
            "You May Also Like\n"
            "Second paragraph of the story.\n"
            "SEE ALSO:\n"
            "Third paragraph of the story.",
            "https://example.com/story",
        )
        self.assertNotIn("You May Also Like", text)
        self.assertNotIn("SEE ALSO", text)
        for part in ("First paragraph", "Second paragraph", "Third paragraph"):
            self.assertIn(part, text)

    def test_sentence_starting_with_label_word_is_kept(self):
        body = (
            "Related lawsuits have been filed in three states over the same disclosure, "
            "according to the filing.\n"
            "Recommended settings for the new phone are listed on the support page."
        )
        self.assertEqual(article_extractor._strip_recirculation_labels(body), body)


if __name__ == "__main__":
    unittest.main()
