"""
Manual feed addition diagnostic to verify articles appear after adding a feed.

This test validates that when a feed is added:
1. The feed is added to the database
2. Articles are fetched during refresh
3. Articles are visible when querying

This is intentionally outside tests/: it uses a real network feed and the
active application database, so it must never run during default pytest.

Bug being diagnosed: Race condition where refresh_feeds() was called before 
articles were fetched, causing the empty article list to be cached with
fully_loaded=True.
"""

import os
import sys
import sqlite3

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import db
from core.config import ConfigManager
from providers.local import LocalProvider


def test_add_feed_and_get_articles():
    """Test that adding a feed and refreshing returns articles."""
    # Use the existing database
    db.init_db()
    
    config = ConfigManager()
    provider = LocalProvider(config)
    
    # Test URL - Buzzsprout feed
    feed_url = "https://www.buzzsprout.com/2385172"
    category = "Test"
    
    # First, remove any existing feed with this URL
    conn = db.get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM articles WHERE feed_id IN (SELECT id FROM feeds WHERE url LIKE ?)", ('%buzzsprout%',))
        c.execute("DELETE FROM feeds WHERE url LIKE ?", ('%buzzsprout%',))
        conn.commit()
        print("Cleaned up existing feed")
    finally:
        conn.close()
    
    # Step 1: Add the feed
    print(f"Adding feed: {feed_url}")
    result = provider.add_feed(feed_url, category)
    assert result, "add_feed() should return True"
    print("Feed added successfully")
    
    # Step 2: Verify feed exists in database
    feeds = provider.get_feeds()
    matching = [f for f in feeds if "buzzsprout" in f.url.lower() or "disability" in f.title.lower()]
    assert len(matching) == 1, f"Expected 1 matching feed, got {len(matching)}"
    feed = matching[0]
    print(f"Feed in DB: {feed.title} (id={feed.id})")
    
    # Step 3: Check articles BEFORE refresh (should be 0)
    articles_before = provider.get_articles(feed_id=feed.id)
    print(f"Articles before refresh: {len(articles_before)}")
    
    # Step 4: Run refresh (simulates _run_refresh)
    print("Running refresh...")
    refresh_count = 0
    def progress_cb(state):
        nonlocal refresh_count
        new_items = state.get("new_items", 0)
        if new_items > 0:
            refresh_count += new_items
            print(f"  Progress: {state.get('title')} - {new_items} new items")
    
    provider.refresh(progress_cb, force=True)
    print(f"Refresh complete, found {refresh_count} total new items")
    
    # Step 5: Check articles AFTER refresh
    articles_after = provider.get_articles(feed_id=feed.id)
    print(f"Articles after refresh: {len(articles_after)}")
    
    # Assertions
    assert len(articles_after) > 0, "Feed should have articles after refresh"
    assert len(articles_after) >= 10, f"Expected at least 10 articles, got {len(articles_after)}"
    
    # Verify articles have media URLs (it's a podcast feed)
    articles_with_media = [a for a in articles_after if a.media_url]
    print(f"Articles with media: {len(articles_with_media)}")
    assert len(articles_with_media) > 0, "Podcast feed should have articles with media URLs"
    
    print("\n✓ TEST PASSED: Feed add + refresh workflow works correctly")


def test_paged_articles_after_add():
    """Test that get_articles_page returns correct results after add+refresh."""
    db.init_db()
    
    config = ConfigManager()
    provider = LocalProvider(config)
    
    feed_url = "https://www.buzzsprout.com/2385172"
    
    # Clean up first
    conn = db.get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM articles WHERE feed_id IN (SELECT id FROM feeds WHERE url LIKE ?)", ('%buzzsprout%',))
        c.execute("DELETE FROM feeds WHERE url LIKE ?", ('%buzzsprout%',))
        conn.commit()
    finally:
        conn.close()
    
    # Add and refresh in one go (simulates what _add_feed_thread does)
    print("Adding feed...")
    provider.add_feed(feed_url, "Test")
    
    print("Refreshing...")
    provider.refresh(lambda s: None, force=True)
    
    # Get feed ID
    feeds = provider.get_feeds()
    feed = [f for f in feeds if "buzzsprout" in f.url.lower() or "disability" in f.title.lower()][0]
    
    # Test get_articles_page (used by UI)
    page, total = provider.get_articles_page(feed.id, offset=0, limit=50)
    print(f"get_articles_page: {len(page)} articles, total={total}")
    
    assert total > 0, "Total should be > 0"
    assert len(page) > 0, "Page should have articles"
    
    print("\n✓ TEST PASSED: Paged articles work correctly")


if __name__ == "__main__":
    print("=" * 60)
    print("Test 1: Add feed and get articles")
    print("=" * 60)
    test_add_feed_and_get_articles()
    
    print()
    print("=" * 60)
    print("Test 2: Paged articles after add")
    print("=" * 60)
    test_paged_articles_after_add()
    
    print()
    print("All tests passed!")
