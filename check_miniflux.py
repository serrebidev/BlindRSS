# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import sys
sys.path.insert(0, '.')
import requests
import json

with open(r'C:\Users\admin\Portable\BlindRSS\config.json', 'r') as f:
    config_data = json.load(f)

miniflux_url = config_data.get('providers', {}).get('miniflux', {}).get('url')
api_key = config_data.get('providers', {}).get('miniflux', {}).get('api_key')

headers = {'X-Auth-Token': api_key}

# Get feed details
resp = requests.get(f'{miniflux_url}/v1/feeds/24', headers=headers)
feed = resp.json()

print('Feed details from Miniflux:')
print(f'  Title: {feed.get("title")}')
print(f'  Feed URL: {feed.get("feed_url")}')
print(f'  Parsing error count: {feed.get("parsing_error_count")}')
print(f'  Parsing error message: {feed.get("parsing_error_message")}')
print(f'  Disabled: {feed.get("disabled")}')
print(f'  Last refresh: {feed.get("checked_at")}')

# Get entries for this feed
print('\nGetting entries...')
resp = requests.get(f'{miniflux_url}/v1/feeds/24/entries', headers=headers)
data = resp.json()
print(f'  Total entries: {data.get("total", 0)}')
entries = data.get('entries', [])
print(f'  Returned entries: {len(entries)}')
if entries:
    print('  First 3:')
    for e in entries[:3]:
        print(f'    - {e.get("title", "")[:50]}')
else:
    print('  No entries!')
    
# Try getting ALL entries for this feed with different params
print('\nTrying with different params...')
resp = requests.get(f'{miniflux_url}/v1/feeds/24/entries?limit=100&direction=desc', headers=headers)
data = resp.json()
print(f'  Total: {data.get("total", 0)}')
print(f'  Entries: {len(data.get("entries", []))}')
