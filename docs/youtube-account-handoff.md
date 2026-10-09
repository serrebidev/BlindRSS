# YouTube account work: handoff to Muse

User requests: fix the unclosable YouTube Account window; add one
Recommendations feed containing videos; automatically update the whole
connected account; commit and release. User has now asked for a commit so
Muse can finish the work. No release of these changes has been started.

Implemented:

- Explicit modal close for Close, Escape, and the window-close/Alt+F4 path.
- Signed-in YouTube TV home-page recommendations, cached privately in
  `rss.db` and exposed alongside every RSS provider through the factory.
- Account-scoped read/favorite/deletion state; sign-out hides account rows.
- Subscription discovery and recommendations update together every 15
  minutes while running, independently of longer RSS refresh intervals.
- Dialog labels and help describe whole-account updates.
- Review fixes for preserving cached RSS history, private chapter caching,
  and category rename/move tracking.

Verification so far:

- Live authenticated read-only recommendation requests succeeded; parsed
  video IDs, titles, and authors. No credentials were logged.
- Latest focused run: 39 tests passed across YouTube account, recommendations,
  modal close, and refresh-loop tests.
- Earlier full run: 2545 passed, 8 skipped, 2 failed. One failure was the
  stale POT catalog; the other was native wx modal-loop interference from
  earlier GUI tests. Modal tests now run in fresh subprocesses and passed
  the focused run. POT regenerated for this handoff commit.
- Full suite has not been rerun after the review fixes.

Finish before release:

1. Check `MainFrame._youtube_sync_finished`: capture the current base rows
   before updating `view_cache`. Otherwise `_get_base_articles_for_current_view`
   can fall back to an already-reconciled cache and skip updating displayed
   rows. Add a focused regression test for cache fallback, preserving an
   unrelated RSS selection/history, and clearing a removed private selection.
2. Avoid creating a rich reader merely to clear a removed recommendation:
   `_render_rich_html("")` calls `_ensure_rich_view`. Clear it only when the
   rich reader already exists. Preserve full-text token invalidation.
3. Run the full offline suite and `git diff --check`; verify the final UI
   reconciliation with the existing focus-preserving rendering helper.
4. Commit remaining fixes, then release and verify all seven assets and Latest.

Release constraints are in `agents.md`. SignPath's release policy was still
invalid because the certificate was CSR pending. The owner's temporary local
self-signed Windows release override remains in effect until revoked.
Latest published release is v2.2.0. Do not manually choose/bump a version.
Cloud-only Muse sessions use the documented cloud workflow; if its Windows
signing remains blocked, a Windows-host session must finish the authorized
local-signing path. Never publish a partial release or delete a draft.

Leave the unrelated untracked `.commandcode/` directory alone.
