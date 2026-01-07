import sys
print(sys.version)
try:
    import derivatives.pricer.main as m
    print("IMPORT_OK")
except Exception as e:
    print("IMPORT_FAIL:", e)
    raise
