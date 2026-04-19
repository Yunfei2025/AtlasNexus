import os 
import site 
import sys 
os.system('mkdir -p ' + site.getusersitepackages()) 
os.system('ln -sf "/Applications/Wind API.app/Contents/python/WindPy.py"' + ' ' + site.getusersitepackages()) ;\
os.system('ln -sf "/Applications/Wind API.app/Contents/python/WindPy.py"' + ' ' + site.getsitepackages()[0]) ;\
os.system('rm -rf ~/.Wind') ;\
os.system('ln -sf ~/Library/Containers/com.wind.mac.api/Data/.Wind ~/.Wind') ;\
print("Current Python Version: " + sys.version) 
print("Current Python Env: " + sys.executable) 
print("WindPy installed at: " + site.getusersitepackages()) 
print("WindPy installed at: " + site.getsitepackages()[0])

import os
import re
config_file = os.path.expanduser("~/.Wind/WFT/users/Auth/user.config")
with open(config_file, "r", encoding="utf-8") as f:
  content = f.read()
match = re.search(r'isAutoLogin="(\d+)"', content)
if match:
  is_auto_login = match.group(1)
  print(is_auto_login)
else:
  print("isAutoLogin not found")
