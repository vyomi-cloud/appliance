# Vyomi install-funnel phone-home (PowerShell — used by Scoop on Windows).
# ───────────────────────────────────────────────────────────────────────
# Counterpart to packaging/common/phone-home.sh — see that file for the
# full design rationale. Same payload shape, same install_id contract,
# same opt-out, just translated to PowerShell because Scoop's post_install
# hook runs PowerShell, not sh.
#
# install_id is persisted at $env:LOCALAPPDATA\Vyomi\install_id which the
# Vyomi CLI later picks up + propagates into the Multipass VM via
# VYOMI_INSTALL_ID so DOWNLOADED → INSTALLED stays the same row.
#
# Required parameter: -Channel scoop  (only "scoop" supported on Windows
# today; keeping it parameterised so a future winget hook can reuse this
# script with -Channel winget).
#
# Opt-out: set $env:VYOMI_NO_TELEMETRY=1 in the shell that runs scoop.
# ───────────────────────────────────────────────────────────────────────

param(
  [string]$Channel = "scoop",
  [string]$Version = ""
)

# Hard opt-out — exit before doing any work.
if ($env:VYOMI_NO_TELEMETRY -and $env:VYOMI_NO_TELEMETRY -ne "0") {
  exit 0
}

try {
  $portalBase = if ($env:VYOMI_PHONE_HOME_URL) {
    $env:VYOMI_PHONE_HOME_URL
  } else {
    "https://vyomi.cloud"
  }
  $portalUrl = "$portalBase/api/install/register"

  # Persist install_id under %LOCALAPPDATA%\Vyomi to keep it per-user,
  # surviving package upgrades / uninstalls.
  $vyomiDir = Join-Path $env:LOCALAPPDATA "Vyomi"
  if (-not (Test-Path $vyomiDir)) {
    New-Item -ItemType Directory -Path $vyomiDir -Force | Out-Null
  }
  $idFile = Join-Path $vyomiDir "install_id"

  $installId = $null
  if (Test-Path $idFile) {
    $installId = (Get-Content $idFile -Raw -ErrorAction SilentlyContinue).Trim()
  }

  # Upgrade-continuity probe — see packaging/common/phone-home.sh for the
  # full rationale. On a `scoop update vyomi` over an existing install
  # the marker file may be missing (v2.0.5 didn't write it) but the
  # appliance is still running with a stable install_id in STATE. We
  # adopt that id so the portal funnel row stays continuous. Fail-soft.
  if (-not $installId -or $installId.Length -lt 8) {
    foreach ($probeUrl in @("http://vyomi.local:9000", "http://127.0.0.1:9000")) {
      try {
        $r = Invoke-WebRequest -Uri "$probeUrl/api/runtime/install-id" `
                                -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
          $j = $r.Content | ConvertFrom-Json
          if ($j.install_id -and $j.install_id.Length -ge 8) {
            $installId = $j.install_id
            break
          }
        }
      } catch { }
    }
  }

  if (-not $installId -or $installId.Length -lt 8) {
    # 16 random hex chars to match the POSIX sh script.
    $bytes = New-Object byte[] 8
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $installId = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
  }

  # Persist whichever id we ended up with (random OR appliance-probed)
  # so the next phone-home + the CLI launcher's env-export see it.
  $current = if (Test-Path $idFile) {
    (Get-Content $idFile -Raw -ErrorAction SilentlyContinue).Trim()
  } else { "" }
  if ($current -ne $installId) {
    Set-Content -Path $idFile -Value $installId -NoNewline -ErrorAction SilentlyContinue
  }

  if (-not $Version) {
    $versionFile = Join-Path (Split-Path -Parent $PSCommandPath) "VERSION"
    if (Test-Path $versionFile) {
      $Version = (Get-Content $versionFile -Raw -ErrorAction SilentlyContinue).Trim()
    } else {
      $Version = "unknown"
    }
  }

  $payload = @{
    install_id = $installId
    version    = $Version
    host_os    = "win32"
    channel    = $Channel
    state      = "DOWNLOADED"
  } | ConvertTo-Json -Compress

  # Fire and forget. -TimeoutSec 3 so the user isn't blocked.
  # -UseBasicParsing keeps us compatible with PowerShell 5.1 (Win10/11).
  # SilentlyContinue swallows any net failure — install must never fail
  # because telemetry was unreachable.
  Invoke-WebRequest -Uri $portalUrl `
                    -Method POST `
                    -Body $payload `
                    -ContentType 'application/json' `
                    -Headers @{ 'User-Agent' = "vyomi-postinst/$Version ($Channel)" } `
                    -TimeoutSec 3 `
                    -UseBasicParsing `
                    -ErrorAction SilentlyContinue | Out-Null
} catch {
  # Swallow everything. Telemetry must never break an install.
}

exit 0
