#!/usr/bin/env python3
import sys
p='update-data.log'
try:
    b=open(p,'rb').read()
    s=b.decode('utf-16',errors='replace')
    lines=s.splitlines()
    for line in lines[-400:]:
        print(line)
except Exception as e:
    print('ERR',e)
