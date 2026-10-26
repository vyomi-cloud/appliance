<#
  End-to-end validation of the Vyomi Windows MSI (run on a clean x64 Windows box,
  as Administrator — the GitHub windows-latest runner is both).

  Scenario A — fresh install:   install NEW → check → uninstall → check clean
  Scenario B — upgrade:         install PREV → install NEW over it → check that
                                exactly one Vyomi entry remains at NEW → uninstall
  Checks: msiexec exit codes, install dir + bundle files, VERSION, the compiled
  bin\vyomi.exe (no host PowerShell script — winget policy), system PATH entry
  (present once, removed on uninstall), Start-menu shortcut (vyomi.exe up),
  Add/Remove Programs entry, `vyomi help` / `vyomi doctor` run from a fresh
  shell, Authenticode status (informational), and a clean uninstall.

  It cannot run `vyomi up`: that boots the appliance in a Multipass VM, and
  GitHub-hosted runners have no nested virtualization.

    pwsh tests/installer/validate-msi.ps1 -Msi new.msi [-PrevMsi old.msi] -Version 3.0.8 [-OutDir out]

  Exit 0 = every check passed. Writes out/summary.md, out/results.json and the
  verbose msiexec logs to out/.
#>
param(
  [Parameter(Mandatory)] [string] $Msi,
  [string] $PrevMsi = "",
  [Parameter(Mandatory)] [string] $Version,
  [string] $OutDir = "msi-validation",
  # When set, the MSI must carry a Valid Authenticode signature from a
  # certificate whose subject contains this text (e.g. "Vyomi Cloud"), also
  # when it carries the browser's downloaded-from-the-internet mark.
  [string] $ExpectSigner = ""
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$Msi = (Resolve-Path $Msi).Path
if ($PrevMsi) { $PrevMsi = (Resolve-Path $PrevMsi).Path }

$InstallDir = Join-Path $env:ProgramFiles "Vyomi"
$BinDir     = Join-Path $InstallDir "bin"
$Exe        = Join-Path $BinDir "vyomi.exe"
$Shortcut   = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\Vyomi\Vyomi appliance.lnk"
$Results    = New-Object System.Collections.Generic.List[object]

function Check([string]$Scenario, [string]$Name, [bool]$Ok, [string]$Detail = "") {
  $Results.Add([pscustomobject]@{ scenario = $Scenario; check = $Name; ok = $Ok; detail = $Detail })
  $mark = if ($Ok) { "PASS" } else { "FAIL" }
  Write-Host ("[{0}] {1}: {2}{3}" -f $mark, $Scenario, $Name, $(if ($Detail) { " — $Detail" } else { "" }))
}

function MachinePath { [Environment]::GetEnvironmentVariable("Path", "Machine") }

function VyomiEntries {
  $keys = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
          "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
  @(Get-ItemProperty $keys -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -eq "Vyomi" })
}

function RunMsiexec([string]$Scenario, [string]$Action, [string[]]$MsiArgs, [string]$Log) {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $p = Start-Process msiexec.exe -ArgumentList ($MsiArgs + @("/qn", "/norestart", "/l*v", "`"$Log`"")) -Wait -PassThru
  $sw.Stop()
  # 0 = success, 3010 = success, reboot required
  Check $Scenario "$Action exits cleanly" ($p.ExitCode -in 0, 3010) "msiexec exit $($p.ExitCode) in $([int]$sw.Elapsed.TotalSeconds)s"
  return $p.ExitCode
}

function CheckInstalled([string]$Scenario, [string]$Expected) {
  Check $Scenario "install dir exists" (Test-Path $InstallDir) $InstallDir
  Check $Scenario "bin\vyomi.exe present" (Test-Path $Exe)
  foreach ($f in "server.py", "VERSION", "docker-compose.appliance.yml", "requirements.txt", "core", "routes", "static", "scripts\cloud-learn") {
    Check $Scenario "bundle file $f" (Test-Path (Join-Path $InstallDir $f))
  }
  Check $Scenario "no host PowerShell launcher (winget policy)" (-not (Test-Path (Join-Path $InstallDir "scripts\cloud-learn.ps1")))
  $ver = if (Test-Path "$InstallDir\VERSION") { (Get-Content "$InstallDir\VERSION" -Raw).Trim() } else { "" }
  Check $Scenario "VERSION file is $Expected" ($ver -eq $Expected) "found '$ver'"

  $entries = VyomiEntries
  Check $Scenario "exactly one Add/Remove Programs entry" ($entries.Count -eq 1) "found $($entries.Count)"
  if ($entries.Count -ge 1) {
    Check $Scenario "Add/Remove Programs version is $Expected" ($entries[0].DisplayVersion -eq $Expected) "found '$($entries[0].DisplayVersion)'"
  }

  $hits = @((MachinePath) -split ";" | Where-Object { $_.TrimEnd("\") -ieq $BinDir.TrimEnd("\") })
  Check $Scenario "system PATH has the bin dir exactly once" ($hits.Count -eq 1) "found $($hits.Count)"

  Check $Scenario "Start-menu shortcut exists" (Test-Path $Shortcut) $Shortcut
  if (Test-Path $Shortcut) {
    $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)
    Check $Scenario "shortcut targets vyomi.exe up" (($lnk.TargetPath -ieq $Exe) -and ($lnk.Arguments -eq "up")) "$($lnk.TargetPath) $($lnk.Arguments)"
  }

  # A brand-new shell sees only the machine PATH: this is what a user gets.
  $fresh = "set `"PATH=$(MachinePath);C:\Windows\System32`" && where vyomi"
  $where = cmd /c $fresh 2>&1 | Out-String
  Check $Scenario "'vyomi' resolves on PATH in a new shell" ($LASTEXITCODE -eq 0 -and $where -match "vyomi.exe") $where.Trim()

  foreach ($cmd in "help", "doctor") {
    $out = & $Exe $cmd 2>&1 | Out-String
    $code = $LASTEXITCODE
    $out | Set-Content (Join-Path $OutDir "$Scenario-vyomi-$cmd.txt")
    Check $Scenario "vyomi $cmd exits 0" ($code -eq 0) ("exit $code; " + ($out.Trim() -split "`n" | Select-Object -First 1))
    Check $Scenario "vyomi $cmd prints output" ($out.Trim().Length -gt 0)
  }
}

function CheckRemoved([string]$Scenario) {
  $left = @(Get-ChildItem $InstallDir -Recurse -File -ErrorAction SilentlyContinue)
  Check $Scenario "uninstall removes installed files" ($left.Count -eq 0) "$($left.Count) file(s) left"
  Check $Scenario "uninstall removes the Add/Remove Programs entry" ((VyomiEntries).Count -eq 0)
  $hits = @((MachinePath) -split ";" | Where-Object { $_.TrimEnd("\") -ieq $BinDir.TrimEnd("\") })
  Check $Scenario "uninstall removes the PATH entry" ($hits.Count -eq 0) "found $($hits.Count)"
  Check $Scenario "uninstall removes the Start-menu shortcut" (-not (Test-Path $Shortcut))
}

# ── Package itself ────────────────────────────────────────────────────────
$sig = Get-AuthenticodeSignature $Msi
Write-Host "Authenticode: $($sig.Status) $($sig.SignerCertificate.Subject)"
if (-not $ExpectSigner) {
  $Results.Add([pscustomobject]@{ scenario = "package"; check = "Authenticode signature (informational)"; ok = $true; detail = "$($sig.Status)" })
} else {
  Check "package" "Authenticode signature is Valid" ($sig.Status -eq "Valid") "$($sig.Status): $($sig.StatusMessage)"
  Check "package" "signed by '$ExpectSigner'" ("$($sig.SignerCertificate.Subject)" -like "*$ExpectSigner*") "$($sig.SignerCertificate.Subject)"
  Check "package" "signature is timestamped" ($null -ne $sig.TimeStamperCertificate) "$($sig.TimeStamperCertificate.Subject)"
  # What a user gets: the browser tags downloads with Zone.Identifier (ZoneId=3,
  # Internet). The signature must still verify on that copy.
  $dl = Join-Path $OutDir ("downloaded-" + (Split-Path $Msi -Leaf))
  Copy-Item $Msi $dl -Force
  Set-Content -Path $dl -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3`r`nHostUrl=https://github.com/vyomi-cloud/appliance/releases/"
  $dsig = Get-AuthenticodeSignature $dl
  Check "package" "downloaded (internet-zone) copy verifies" ($dsig.Status -eq "Valid") "$($dsig.Status)"
  Remove-Item $dl -Force
}

# ── Scenario A: fresh install ─────────────────────────────────────────────
if ((VyomiEntries).Count -gt 0) { throw "Vyomi is already installed on this machine; run on a clean box." }
RunMsiexec "fresh" "install $Version" @("/i", "`"$Msi`"") "$OutDir\fresh-install.log" | Out-Null
CheckInstalled "fresh" $Version
RunMsiexec "fresh" "uninstall $Version" @("/x", "`"$Msi`"") "$OutDir\fresh-uninstall.log" | Out-Null
CheckRemoved "fresh"

# ── Scenario B: upgrade from the previous release ─────────────────────────
if ($PrevMsi) {
  $prevVer = (Get-Item $PrevMsi).BaseName -replace '^cloud-learn-', '' -replace '-x64$', ''
  RunMsiexec "upgrade" "install previous $prevVer" @("/i", "`"$PrevMsi`"") "$OutDir\upgrade-prev-install.log" | Out-Null
  Check "upgrade" "previous $prevVer installed" ((VyomiEntries).Count -eq 1)
  RunMsiexec "upgrade" "upgrade $prevVer → $Version" @("/i", "`"$Msi`"") "$OutDir\upgrade-install.log" | Out-Null
  CheckInstalled "upgrade" $Version
  RunMsiexec "upgrade" "uninstall $Version" @("/x", "`"$Msi`"") "$OutDir\upgrade-uninstall.log" | Out-Null
  CheckRemoved "upgrade"
} else {
  $Results.Add([pscustomobject]@{ scenario = "upgrade"; check = "upgrade from previous release"; ok = $true; detail = "skipped: no previous MSI" })
}

# ── Report ────────────────────────────────────────────────────────────────
$failed = @($Results | Where-Object { -not $_.ok })
$Results | ConvertTo-Json -Depth 3 | Set-Content "$OutDir\results.json"
$md = @("### Vyomi MSI $Version — $($Results.Count - $failed.Count)/$($Results.Count) checks passed", "",
        "| | Scenario | Check | Detail |", "|---|---|---|---|")
foreach ($r in $Results) {
  $md += "| $(if ($r.ok) { '✅' } else { '❌' }) | $($r.scenario) | $($r.check) | $(($r.detail -replace '\|', '\|' -replace "`r?`n", ' '))  |"
}
$md += "", "_Not covered: ``vyomi up`` (boots a Multipass VM; GitHub runners have no nested virtualization)._"
$md -join "`n" | Set-Content "$OutDir\summary.md"
Write-Host ""
Write-Host "$($Results.Count - $failed.Count)/$($Results.Count) checks passed"
if ($failed.Count) { exit 1 }
