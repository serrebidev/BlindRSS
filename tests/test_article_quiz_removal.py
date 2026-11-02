# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Embedded CSS-only quizzes must never reach either reader.

Modeled on the widget How-To Geek puts mid-article: radio inputs for navigation
and for each question sit directly in one container, and the question panels are
ordinary <section>/<p> text that no chrome rule can tell from prose.
"""

from core import article_extractor, article_html, utils

URL = "https://www.howtogeek.com/phone-keyboard/"

PROSE = (
    "I spent a whole month typing on a phone with a physical keyboard, and the "
    "experience changed how I think about touchscreens and the apps I reach for "
    "every single day. "
)
AFTER = (
    "However, my favorite thing about the keyboard turned out to be the shortcuts, "
    "because every key can launch an app or a contact from anywhere on the phone. "
)

QUIZ = """
<div class="w-display-card-vignette"><div class="vq">
  <input type="radio" id="vq-s0" name="vq-nav" checked>
  <input type="radio" id="vq-s1" name="vq-nav">
  <input type="radio" id="vq-1a" name="vq-1"><input type="radio" id="vq-1b" name="vq-1">
  <input type="radio" id="vq-2a" name="vq-2"><input type="radio" id="vq-2b" name="vq-2">
  <div class="vq-wrap">
    <section class="vq-panel"><h2>The History of Android OS<br>Trivia Challenge</h2>
    <p>From a scrappy startup to the most popular operating system, how well do you
    know the remarkable journey of Android and everyone who worked on it?</p></section>
    <section class="vq-panel"><p>In what year was Android Inc. originally founded by
    Andy Rubin and his co-founders in California?</p>
    <div class="vq-fb">Correct! Android Inc. was founded in October 2003 in Palo Alto,
    California, before the team pivoted to building software for mobile phones.</div>
    <label class="vq-btn" for="vq-sR">See My Score</label></section>
    <section class="vq-panel"><h2>Your Score</h2><p>Thanks for playing!</p></section>
  </div>
</div></div>
"""


def _page(middle: str) -> str:
    return (
        '<html><head><title>Keyboard phone</title></head><body><main><article>'
        '<section id="article-body">'
        f"<p>{PROSE * 3}</p>{middle}<h2>I love this keyboard</h2><p>{AFTER * 3}</p>"
        "</section></article></main></body></html>"
    )


QUIZ_MARKERS = ("Trivia Challenge", "founded by", "Correct!", "Your Score", "Thanks for playing")


def _assert_quiz_gone_prose_kept(out: str) -> None:
    for marker in QUIZ_MARKERS:
        assert marker not in out, marker
    assert "typing on a phone" in out
    assert "launch an app" in out
    assert "I love this keyboard" in out


def test_quiz_removed_from_classic_reader():
    _assert_quiz_gone_prose_kept(article_extractor._extract_text_any(_page(QUIZ), URL))


def test_quiz_removed_from_rich_view():
    _assert_quiz_gone_prose_kept(article_html.clean_article_html(_page(QUIZ), URL))


def test_quiz_removed_from_extract_from_html_path():
    art = article_extractor.extract_from_html(_page(QUIZ), URL)
    _assert_quiz_gone_prose_kept(art.text)


def test_css_tabs_with_one_radio_group_keep_their_content():
    tabs = (
        '<div class="tabs"><input type="radio" name="tab" id="t1" checked>'
        '<input type="radio" name="tab" id="t2">'
        "<section><p>The first tab explains the real specifications.</p></section></div>"
    )
    page = _page(tabs)
    assert utils.strip_css_quizzes(page) == page


def test_page_wrapper_holding_radios_is_never_removed():
    radios = "".join(f'<input type="radio" name="g{i}">' for i in range(4))
    page = f"<html><body>{radios}<p>{PROSE}</p></body></html>"
    assert PROSE.strip() in utils.strip_css_quizzes(page)
    wrapped = f"<html><body><form>{radios}<p>{PROSE}</p></form></body></html>"
    assert PROSE.strip() in utils.strip_css_quizzes(wrapped)


def test_page_without_radios_is_returned_untouched():
    page = _page("<p>No widget here at all, and <br> this markup stays byte identical.</p>")
    assert utils.strip_css_quizzes(page) == page
    assert utils.strip_css_quizzes("") == ""
