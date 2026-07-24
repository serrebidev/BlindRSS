# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import sqlite3

conn = sqlite3.connect(r'C:\Users\admin\Portable\BlindRSS\rss.db')
c = conn.cursor()

# Check table structure
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = c.fetchall()
print('Tables:', [t[0] for t in tables])

# Check if DB is empty or just no feeds
for table in tables:
    name = table[0]
    c.execute(f'SELECT COUNT(*) FROM {name}')
    count = c.fetchone()[0]
    print(f'  {name}: {count} rows')

conn.close()
