param(
  [string]$EdgeIP = "198.41.200.193",
  [string]$Host = "example.com",
  [int]$TsharkPackets = 200
)

$OutDir = Join-Path $PSScriptRoot "quic_diag"
New-Item -Path $OutDir -ItemType Directory -Force | Out-Null
$OutFile = Join-Path $OutDir "quic_diag_output.txt"
$CaptureFile = Join-Path $OutDir "quic_capture.pcap"

function Write-Log { param($s) $t = Get-Date -Format o; "$t $s" | Tee-Object -FilePath $OutFile -Append }

Write-Log "Starting QUIC diagnostics script"
Write-Log "EdgeIP=$EdgeIP Host=$Host"

Write-Log "`n=== Test-NetConnection to Edge IP ==="
Try {
  $res = Test-NetConnection -ComputerName $EdgeIP -Port 443 -WarningAction SilentlyContinue
  $res | Out-String | Tee-Object -FilePath $OutFile -Append
} catch { $_ | Out-String | Tee-Object -FilePath $OutFile -Append }

Write-Log "`n=== Test-NetConnection to Host ==="
Try { Test-NetConnection -ComputerName $Host -Port 443 | Out-String | Tee-Object -FilePath $OutFile -Append } catch { $_ | Out-String | Tee-Object -FilePath $OutFile -Append }

Write-Log "`n=== curl --http3 (if available) ==="
$curl = Get-Command curl -ErrorAction SilentlyContinue
if ($curl) {
  try {
    $curlOut = & curl --http3 -v --resolve "$Host:443:$EdgeIP" "https://$Host/" 2>&1
    $curlOut | Tee-Object -FilePath $OutFile -Append
  } catch { $_ | Out-String | Tee-Object -FilePath $OutFile -Append }
} else { Write-Log "curl not found on PATH" }

Write-Log "`n=== ncat/nc probe (if available) ==="
$nc = Get-Command ncat -ErrorAction SilentlyContinue
if (-not $nc) { $nc = Get-Command nc -ErrorAction SilentlyContinue }
if ($nc) {
  try {
    Write-Log "Attempting UDP probe (2s timeout)..."
    $ncOut = echo "ping" | & $nc -u $EdgeIP 443 -w 2 2>&1
    $ncOut | Tee-Object -FilePath $OutFile -Append
  } catch { $_ | Out-String | Tee-Object -FilePath $OutFile -Append }
} else { Write-Log "ncat/nc not found on PATH" }

Write-Log "`n=== List suspicious processes ==="
Get-Process | Where-Object { $_.ProcessName -match 'cloudflare|cloudflared|warp|ngrok|tunnel|edge' } | Out-String | Tee-Object -FilePath $OutFile -Append

Write-Log "`n=== Outbound firewall block rules ==="
Try { Get-NetFirewallRule -Direction Outbound -Action Block | Select-Object Name,DisplayName,Enabled | Out-String | Tee-Object -FilePath $OutFile -Append } catch { $_ | Out-String | Tee-Object -FilePath $OutFile -Append }

Write-Log "`n=== tshark capture (if available) ==="
$tshark = Get-Command tshark -ErrorAction SilentlyContinue
if ($tshark) {
  try {
    Write-Log "Capturing up to $TsharkPackets udp packets to $EdgeIP:443 (requires admin rights)"
    & tshark -c $TsharkPackets -f "udp and host $EdgeIP and port 443" -w $CaptureFile 2>&1 | Tee-Object -FilePath $OutFile -Append
    Write-Log "Capture saved to $CaptureFile"
  } catch { $_ | Out-String | Tee-Object -FilePath $OutFile -Append }
} else { Write-Log "tshark not found on PATH" }

Write-Log "Done. Results in $OutFile"
