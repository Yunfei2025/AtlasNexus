@echo off
call D:\ProgramData\Miniconda3\Scripts\activate.bat dev
set curdir=%~dp0
cd /d %curdir%
python main.py

exit


)