#!/usr/bin/env python3
import os,datetime
p='runs'
entries=[(d, os.path.getmtime(os.path.join(p,d))) for d in os.listdir(p) if os.path.isdir(os.path.join(p,d))]
entries.sort(key=lambda x:x[1], reverse=True)
for name,ts in entries[:10]:
    print(name, datetime.datetime.fromtimestamp(ts))
