# Windows AtlasNexus Setup

This guide sets up the Cloudflare tunnel on Windows to serve **anwin.mayunfei.org**

## Prerequisites

1. **Python 3.13** with conda environment `prod`
   ```powershell
   conda create -n prod python=3.13
   ```

2. **Cloudflared** installed
   ```powershell
   choco install cloudflare-warp
   # OR download from: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
   ```

## Setup Steps

### 1. Create `.cloudflared` directory

```powershell
mkdir "$env:USERPROFILE\.cloudflared"
cd "$env:USERPROFILE\.cloudflared"
```

### 2. Copy credentials from Mac

Copy these files from Mac (`/Users/mayunfei/.cloudflared/`) to Windows (`C:\Users\<username>\.cloudflared\`):

- **ff6e80f4-9330-4283-8e3c-85d9641e521a.json** (tunnel credentials)
- **config-anwin.yml** (rename to `config.yml` on Windows)

You can use:
- USB drive
- Cloud sync (Google Drive, Dropbox, OneDrive)
- SCP: `scp mayunfei@<mac-ip>:/Users/mayunfei/.cloudflared/ff6e80f4-9330-4283-8e3c-85d9641e521a.json ~/.cloudflared/`

### 3. Create config.yml on Windows

If copying the file, just rename `config-anwin.yml` → `config.yml`

Otherwise, create `C:\Users\<username>\.cloudflared\config.yml`:

```yaml
tunnel: anwin
credentials-file: ~/.cloudflared/ff6e80f4-9330-4283-8e3c-85d9641e521a.json
ingress:
  - hostname: anwin.mayunfei.org
    service: http://127.0.0.1:8080
  - service: http_status:404
```

### 4. Run the launcher

Run `START_win.bat` from the project directory:

```powershell
# Navigate to project root
cd C:\path\to\FIEngine\bin-v4.0
.\START_win.bat
```

This will:
1. Activate the `prod` conda environment
2. Start the Dash server on http://127.0.0.1:8080
3. Start the Cloudflare tunnel

You should see output like:
```
[3/3] Starting Cloudflare tunnel (anwin → anwin.mayunfei.org)...

  Local:   http://127.0.0.1:8080
  Public:  https://anwin.mayunfei.org

Share https://anwin.mayunfei.org with your friends.
```

### 5. (Optional) Auto-start on Windows boot

To run the tunnel as a service that starts automatically:

```powershell
# Install service
cloudflared service install

# Start service
cloudflared service start
```

Then you don't need to run `START_win.bat` manually.

## Verification

Test locally:
```powershell
curl http://127.0.0.1:8080
```

Test from anywhere:
```powershell
curl https://anwin.mayunfei.org
```

## Multiple Windows Computers

Both Windows computers can share the **same** tunnel (`anwin`) by using the same credentials file (`ff6e80f4-9330-4283-8e3c-85d9641e521a.json`).

Only **one** can be active at a time, but they'll show as different connectors in Cloudflare:
```bash
# On Mac, check both Windows connectors:
cloudflared tunnel info anwin
```

## Files Checklist

- ✅ `START_win.bat` — launcher script (updated)
- ✅ Cloudflare credentials: `ff6e80f4-9330-4283-8e3c-85d9641e521a.json`
- ✅ Tunnel config: `config.yml` (ingress pointing to anwin.mayunfei.org)

## Mac Setup Reference

For comparison, the Mac setup uses:
- Tunnel name: `atlasnexus`
- Domain: `anmac.mayunfei.org`
- Config: `/Users/mayunfei/.cloudflared/config.yml`
- Launcher: `START_mac.command`
