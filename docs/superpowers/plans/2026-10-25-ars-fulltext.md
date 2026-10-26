# Ars Technica Full Text Implementation Plan

**Goal:** Restore all Ars article sections in both readers.

**Architecture:** Share publisher-specific body reconstruction through
`core/article_html.py`; classic extraction converts that body through the
existing text helper. Preserve generic fallbacks and Rich View sanitization.

**Spec:** `docs/superpowers/specs/2026-10-25-ars-fulltext-design.md`

## Task

1. Add offline split-body tests in `tests/test_arstechnica_extraction.py`.
   Verify they fail on the current extractor and rich cleaner.
2. Add the shared body reconstruction and connect both extraction paths.
3. Verify document order, nested sections, single-section pages, host boundaries,
   absent markup, body structure, sanitization and excluded widgets.
4. Run regression tests and compare full extraction against live Ars body blocks.
5. Review the diff, commit with a `fix:` subject, run the canonical release,
   and verify GitHub Latest and all platform assets.

## Validation record

- The original Ars article reproduced the exact 2,197-character cutoff. The
  fix retains 15,475 characters and every paragraph in all six body sections.
  Four additional current Ars articles also retained every body paragraph.
- Nine offline regression cases cover both readers, ordering, nesting, links,
  headings, images, quotes, script removal, host boundaries, missing markup,
  Register navigation, MacRumors lead loss, and ZDNET's related-video wrapper.
  The relevant cases were observed failing before their fixes.
- Expanded live checks sampled two articles from each of fourteen other feeds:
  The Verge, Engadget, Wired, TechCrunch, The Register, TechRadar, Tom's Hardware,
  Neowin, BleepingComputer, Android Authority, 9to5Mac, 9to5Google, MacRumors and
  ZDNET. All sampled article prose survived both readers after the fixes.
  Excluded TechCrunch social-embed text and TechRadar promotional paragraphs
  were reviewed separately from article prose.
- Neowin initially blocked requests. With the user's explicit authorization,
  imported only its Firefox cookie and matching browser identity, then verified
  all 42 substantial paragraphs across its two sampled articles. No cookies or
  downloaded publisher HTML belong in the commit.
- Independent review found no actionable issues in the initial or expanded fix.
- Regenerated the gettext template after the suite found stale source references;
  no UI strings were added by this change.
- Final full suite: 2,690 passed, 8 skipped, 9 subtests passed. `git diff --check`
  passed. Release dry-run verified WSL/Docker and computed patch version v2.5.1.
