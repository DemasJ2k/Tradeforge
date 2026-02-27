@echo off
set PATH=C:\Program Files\nodejs;%PATH%
cd /d D:\Doc\DATA\tradeforge\frontend
call npx next build > D:\Doc\DATA\tradeforge\build_output.txt 2>&1
