@echo off
cd /d "%~dp0"

if not exist cloudflared.exe (
    echo 正在下载 cloudflared...
    powershell -Command "Invoke-WebRequest -Uri https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -OutFile cloudflared.exe"
)

echo 正在启动 Cloudflare Tunnel...
echo 外网地址会显示在下面
cloudflared.exe tunnel --url http://localhost:8080

pause