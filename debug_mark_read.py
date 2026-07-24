# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Debug script to test mark all as read + refresh behavior"""
import sqlite3
import os
from core.config import APP_DIR

DB_FILE = os.path.join(APP_DIR, "rss.db")

def check_unread():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Total articles
    c.execute("SELECT COUNT(*) FROM articles")
    total = c.fetchone()[0]
    
    # Unread articles
    c.execute("SELECT COUNT(*) FROM articles WHERE is_read = 0")
    unread = c.fetchone()[0]
    
    # Read articles
    c.execute("SELECT COUNT(*) FROM articles WHERE is_read = 1")
    read = c.fetchone()[0]
    
    print(f"Total articles: {total}")
    print(f"Unread articles: {unread}")
    print(f"Read articles: {read}")
    
    # Show distribution by feed
    c.execute("""
        SELECT f.title, 
               COUNT(CASE WHEN a.is_read = 0 THEN 1 END) as unread,
               COUNT(CASE WHEN a.is_read = 1 THEN 1 END) as read
        FROM articles a
        JOIN feeds f ON a.feed_id = f.id
        GROUP BY f.id, f.title
        ORDER BY unread DESC
        LIMIT 10
    """)
    
    print("\nTop 10 feeds by unread count:")
    for row in c.fetchall():
        print(f"  {row[0]}: {row[1]} unread, {row[2]} read")
    
    conn.close()

if __name__ == "__main__":
    check_unread()
