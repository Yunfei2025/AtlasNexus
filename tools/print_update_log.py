#!/usr/bin/env python3
import sys
p = 'update-data.log'
try:
    b = open(p,'rb').read()
    print(b.decode('utf-16', errors='replace'))
except FileNotFoundError:
    print('LOG NOT FOUND')
except Exception as e:
    print('ERROR', e)
