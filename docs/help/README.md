# The in-app user guide

`docs/help/<language>.md` is the offline manual BlindRSS shows for Help > User
Guide and for every F1 press. `en.md` is the source document; every other file
is a translation of it.

## Why this is not in the gettext catalogue

`locale/blindrss.pot` holds the interface strings — buttons, menu labels,
messages. A manual is prose, and splitting prose into thousands of tiny msgids
makes it unpleasant to translate and fragile to reword. One Markdown file per
language keeps a translator working on whole paragraphs, and lets them reorder
or expand a section where their language needs it.

## Adding a translation

1. Copy `en.md` to `<code>.md`, where `<code>` is the language code BlindRSS
   uses in `locale/` — `de`, `fr`, `pt_BR`, `zh_CN`, and so on. A regional code
   may be written `pt_BR` or `pt-BR`; both resolve, and `pt.md` is used for any
   Portuguese if no regional file exists.
2. Translate the prose.
3. **Leave every `{#anchor}` marker exactly as it is.** The anchors are the
   topic ids in `core/help_topics.py`, and they are what lets F1 open the right
   section in your language. The heading text beside an anchor should be
   translated; the anchor itself must not be.
4. Do not add or remove sections. `tests/test_help_system.py` checks that every
   translated guide carries the same anchors as `en.md`, so a missing section
   fails the test rather than silently losing F1 for that topic.

A language with no file here falls back to English, and the help window says so
at the top rather than leaving the reader wondering.

## Supported Markdown

The parser (`core/help_docs.py`) reads a deliberately small subset, because the
guide is rendered into a plain text control that a screen reader reads line by
line:

- `# Title` — the document title, once, at the top.
- `## Heading {#anchor}` and `### Heading {#anchor}` — sections. A heading with
  no anchor still appears in the contents list; it just cannot be a jump target.
- `- item` and `1. item` — lists.
- Paragraphs, separated by a blank line. Single newlines inside a paragraph are
  joined, so wrap lines wherever you like.
- `**bold**`, `*italic*`, and `` `code` `` are flattened to plain text.
- `[text](url)` becomes `text (url)`, because an offline reader still wants the
  address and there is nothing to click.

Anything else is passed through as plain text.

## Adding a new topic

1. Add `("my-topic", _("My Topic"))` to `TOPICS` in `core/help_topics.py`.
2. Add `## My Topic {#my-topic}` to `en.md`.
3. Point whatever the topic documents at it — a shortcut command in
   `COMMAND_TOPICS`, a dialog class in `DIALOG_TOPICS`, a notebook tab in
   `NOTEBOOK_PAGE_TOPICS`, a context-menu label in `CONTEXT_MENU_TOPICS`, or a
   `help_context.set_help_topic(control, "my-topic")` call on the control
   itself.

The tests will tell you if the guide and the registry disagree.
