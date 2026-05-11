$ErrorActionPreference = 'Stop'
$logDir = Join-Path $PWD 'logs'
$watch = Join-Path $logDir 'build-500-watch.log'
$out = Join-Path $logDir 'build-500-background.out.log'
$err = Join-Path $logDir 'build-500-background.err.log'
while ($true) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  $p = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Id -eq 6012 }
  if ($p) {
    $tailOut = if (Test-Path $out) { Get-Content $out -Tail 20 -ErrorAction SilentlyContinue } else { @() }
    $tailErr = if (Test-Path $err) { Get-Content $err -Tail 20 -ErrorAction SilentlyContinue } else { @() }
    Add-Content -Path $watch -Value "[$ts] RUNNING pid=6012"
    if ($tailOut) { Add-Content -Path $watch -Value "--- OUT tail ---"; $tailOut | Add-Content -Path $watch }
    if ($tailErr) { Add-Content -Path $watch -Value "--- ERR tail ---"; $tailErr | Add-Content -Path $watch }
  } else {
    Add-Content -Path $watch -Value "[$ts] PROCESS NOT FOUND (pid=6012)"
    break
  }
  Start-Sleep -Seconds 1800
}
