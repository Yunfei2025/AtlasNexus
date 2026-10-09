#!/usr/bin/env python3
import urllib.request
url='http://127.0.0.1:8080/'
try:
    with urllib.request.urlopen(url, timeout=5) as r:
        print('HTTP', r.status)
        data=r.read(500).decode('utf-8',errors='replace')
        for i,l in enumerate(data.splitlines()[:12], start=1):
            print(f'{i:02d}', l)
except Exception as e:
    print('ERR', e)
