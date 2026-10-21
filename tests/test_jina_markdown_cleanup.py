# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Regression tests: read-proxy (Jina) markdown must never reach the reader raw.

Axios gates the direct page fetch, so its articles are recovered through the
Jina read-proxy, which answers in MARKDOWN. The gate-fallback chain used to
hand that markdown to the HTML extractors as if it were page HTML, and the
syntax survived verbatim into the text view: '**Why it matters:**' labels
wrapped in stars, '*   ' bullets leading prose paragraphs, and '[text](url)'
links spoken with their URLs. The Google News path always converted proxy
markdown first; the gate fallback now does too (_download_via_jina_as_text).

Fixture below is the proxy rendering of the reference article
https://www.axios.com/2026/10/21/when-ai-models-refuse-to-fight-hackers
trimmed to the paragraphs that carry each artifact class.
"""

import types

import core.article_extractor as article_extractor
import core.utils as utils


AXIOS_JINA_RESPONSE = (
    "Title: When AI models refuse to fight hackers\n"
    "\n"
    "URL Source: http://www.axios.com/2026/10/21/when-ai-models-refuse-to-fight-hackers\n"
    "\n"
    "Markdown Content:\n"
    "In the race to fend off [AI-enabled cyber threats](https://www.axios.com/2026/09/17/ai-cyber-doomsday-hacking-threats), "
    "security teams are confronting a new problem: The AI models they rely on to investigate attacks can suddenly refuse to help.\n"
    "\n"
    "**Why it matters:** While [AI](https://www.axios.com/technology/automation-and-ai) giants race to build AI tools "
    "that can respond quickly to hacking or other malicious online threats, strict guardrails on their most powerful "
    "models lock out defenders mid-investigation, leaving them scrambling for alternatives at critical moments.\n"
    "\n"
    "**What's happening:** OpenCode, an open-source AI coding agent, said it was compromised over the weekend, "
    "allowing attackers to obtain API keys belonging to some customers.\n"
    "\n"
    "*   OpenCode [said](https://x.com/opencode/status/2111519637049319818) the breach was \"related to a large scale "
    "distillation attack that impacted 1.4% of OpenCode Console users.\"\n"
    "\n"
    "*   [OpenAI](https://x.com/thsottiaux/status/2112034063934742720), [Google](https://x.com/EvanOtero/status/2111591525876474100) "
    "and [Anthropic](https://x.com/lydiahallie/status/2111563956666110287) have said they worked with affected customers "
    "to revoke exposed API keys and address unauthorized usage charges.\n"
    "\n"
    "**Zoom in:** Raad [said on X](https://x.com/thdxr/status/2111831348336091179) that frontier AI models initially "
    "helped investigate the breach but then \"started refusing.\"\n"
)

GATE_HTML = (
    "<html><head><title>Attention Required! | Cloudflare</title></head><body>"
    "<div class='cf-browser-verification'>Checking your browser before accessing axios.com</div>"
    "</body></html>"
)

ARTICLE_URL = "https://www.axios.com/2026/10/21/when-ai-models-refuse-to-fight-hackers"


def _resp(status_code, text, url=""):
    return types.SimpleNamespace(status_code=status_code, text=text, encoding="utf-8", url=url)


def _assert_no_markdown_artifacts(text):
    assert "**" not in text
    assert "](" not in text
    assert "http://" not in text and "https://" not in text
    for line in text.splitlines():
        assert not line.lstrip().startswith("* "), line
        assert not line.lstrip().startswith("# "), line


def test_markdown_links_to_text_strips_axios_artifacts():
    body = AXIOS_JINA_RESPONSE.split("Markdown Content:", 1)[1]
    text = article_extractor._markdown_links_to_text(body)
    _assert_no_markdown_artifacts(text)
    # Labels keep their words, links keep only their link text, bullets read as prose.
    assert "Why it matters: While AI giants race to build AI tools" in text
    assert "What's happening: OpenCode, an open-source AI coding agent" in text
    assert 'OpenCode said the breach was "related to a large scale distillation attack' in text
    assert "OpenAI, Google and Anthropic have said they worked with affected customers" in text
    assert "Zoom in: Raad said on X that frontier AI models" in text
    assert "In the race to fend off AI-enabled cyber threats, security teams" in text


def test_markdown_links_to_text_handles_other_emphasis_shapes():
    md = (
        "## Section heading\n"
        "A *stressed* word, an _understated_ one, a __bold claim__ and ~~old news~~.\n"
        "![chart alt text](https://example.com/chart.png)\n"
        "Read [the reference][1] and the [nested](https://example.com/a_(b)) link.\n"
        "> A quoted line from the story.\n"
        "---\n"
        "snake_case_names and 2 \\* 3 math stay readable.\n"
        "[1]: https://example.com/reference\n"
    )
    text = article_extractor._markdown_links_to_text(md)
    _assert_no_markdown_artifacts(text)
    assert "Section heading" in text
    assert "A stressed word, an understated one, a bold claim and old news." in text
    assert "chart.png" not in text and "chart alt text" not in text
    assert "Read the reference and the nested link." in text
    assert "A quoted line from the story." in text
    assert "snake_case_names" in text
    assert "2 * 3 math stay readable." in text


def test_gate_fallback_via_jina_returns_plain_text(monkeypatch):
    # Direct fetch and the impersonated refetch both hit the gate; Jina recovers
    # the article as markdown. What _fetch_page hands to the extractors must
    # already be plain text — and stay plain through extraction + postprocess.
    def fake_get(url, **kwargs):
        if "r.jina.ai" in url:
            return _resp(200, AXIOS_JINA_RESPONSE)
        return _resp(200, GATE_HTML)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    res = article_extractor._fetch_page(ARTICLE_URL)
    assert res.blocked is False
    assert res.html
    _assert_no_markdown_artifacts(res.html)
    assert "Why it matters: While AI giants race to build AI tools" in res.html

    text = article_extractor._postprocess_extracted_text(
        article_extractor._extract_text_any(res.html, ARTICLE_URL), ARTICLE_URL
    )
    _assert_no_markdown_artifacts(text)
    assert 'OpenCode said the breach was "related to a large scale distillation attack' in text
    assert "OpenAI, Google and Anthropic have said they worked with affected customers" in text
