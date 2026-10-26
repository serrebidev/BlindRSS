# Ars Technica full text

The reported Starlink article contains six `div.post-content` sections inside
one article. Classic extraction returns only the first 2,197 characters. Rich
View's generic pruning also discards later sections.

## Approaches

- Loosen generic extraction: broader regression risk and still depends on
  heuristics recognizing every section.
- Reconstruct Ars's explicit body sections: chosen because it scopes the fix
  to verified publisher markup and serves both readers.

Rebuild the first article's body sections in document order, excluding interlude
widgets and page anchors. Reuse that reconstruction for classic conversion and
Rich View sanitization. Rich View must skip generic text pruning for this known
body. Keep headings, links, images, tables and ordinary prose. If the host or body
structure does not match, retain normal extraction. No dependencies, settings,
version edits or UI changes are required.

Acceptance: both readers retain every section without duplicates or page chrome;
offline regression tests and live checks include the reported article. Commit
the verified change, run `build.bat release`, and verify updater-visible assets.

## Broader feed audit

The user requested checks of at least ten additional technology feeds before
release. Test two recent articles from fourteen feeds. Review paragraph coverage
against publisher body markup in both readers; distinguish omitted article prose
from excluded promotions and social embeds. Report blocked pages explicitly.

The live audit confirmed additional body-selection failures: The Register's rich
reader chooses navigation instead of its `.bodytext` content, MacRumors loses its
lead and appends unrelated stories instead of retaining `article .js-content`,
and ZDNET places article prose inside `.zd-related-stories-flow`, which generic
related-widget filters discard. Extend the same host-scoped reconstruction to
these explicit body containers and preserve sanitizer protections. Leave other
publishers on their existing extraction path.
