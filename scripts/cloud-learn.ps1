#!/usr/bin/env pwsh
# -------------------------------------------------------------------------
# vyomi - Windows launcher (PowerShell)
#
# Ported to parity with the bash launcher (scripts/cloud-learn) for the
# current appliance architecture: a generic Ubuntu 24.04 Multipass VM is
# booted with cloud-init, the source tree is synced in via tar+transfer
# (NOT `multipass mount` - that fails through install sandboxes), and the
# docker-compose stack runs INSIDE the VM. The host bridges localhost
# 9000/9443 -> the VM IP via `netsh interface portproxy`.
#
# Parity-with-bash notes:
#   - tar+transfer workspace sync (was: multipass mount)
#   - runtime_bridge.py transferred to the VM + run as a systemd unit
#   - cloud-init installs avahi-daemon/libnss-mdns + sets hostname=vyomi
#   - Multipass auto-install via winget
#   - direct-IP health probe (was: slow `multipass exec` polling)
#   - netsh portproxy localhost bridge + browser auto-open + URL banner
#   - `upgrade` command (pull vyomi/appliance:<latest>, recreate simulator)
#
# Deferred (HTTP works; HTTPS/extras land in a follow-up):
#   - mkcert/TLS provisioning (no https://localhost:9443 green padlock yet)
#   - LXD<->docker iptables one-shot, legacy-VM mDNS fixup
# -------------------------------------------------------------------------
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$RemainingArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# -- Env mirroring (CLOUDLEARN_* <-> VYOMI_*) -------------------------------
# Keep both prefixes in sync so legacy CLOUD_LEARN_* and new VYOMI_* both work.
function Get-EnvAny {
  param([string[]]$Names, [string]$Default = '')
  foreach ($n in $Names) {
    $v = [Environment]::GetEnvironmentVariable($n)
    if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
  }
  return $Default
}

function Get-RecommendedSizing {
  # Host-aware VM sizing that ALWAYS leaves the host enough RAM so a heavy
  # first-boot image pull can't starve (and freeze) the machine. The old
  # hardcoded 8G default froze 8GB laptops by handing the VM the whole box.
  $cpu = [Environment]::ProcessorCount
  $memGb = 8.0
  try { $memGb = ((Get-CimInstance -ClassName Win32_ComputerSystem).TotalPhysicalMemory) / 1GB } catch { }
  $freeGb = 30.0
  try { $freeGb = ([System.IO.DriveInfo]::new($env:SystemDrive)).AvailableFreeSpace / 1GB } catch { }
  # Reserve ~4GB for the host OS/hypervisor, then give the VM 85% of the rest.
  $vmMem = [int][Math]::Floor(($memGb - 4) * 0.85)
  if ($vmMem -lt 2)  { $vmMem = 2 }     # below-spec host: tiny VM, but never starve the host
  if ($vmMem -gt 16) { $vmMem = 16 }    # the stack gains little past ~16GB
  $vmCpus = [int][Math]::Max(2, [Math]::Min([Math]::Max($cpu - 1, 1), [Math]::Ceiling($vmMem / 2.0)))
  $vmDisk = [int][Math]::Min(40, [Math]::Max(20, [Math]::Floor($freeGb * 0.5)))
  return @{ MemGb = $vmMem; Cpus = $vmCpus; DiskGb = $vmDisk }
}

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = (Resolve-Path (Get-EnvAny @('VYOMI_HOME','CLOUD_LEARN_HOME') (Join-Path $ScriptPath '..'))).Path
$ProjectName = Get-EnvAny @('VYOMI_PROJECT_NAME','CLOUD_LEARN_PROJECT_NAME') 'cloud-learn'
$ComposeFile = Get-EnvAny @('VYOMI_COMPOSE_FILE','CLOUD_LEARN_COMPOSE_FILE') (Join-Path $RootDir 'docker-compose.appliance.yml')
$ParentOs = 'windows'
$DistributionMode = 'appliance'
$RuntimeContext = (Get-EnvAny @('VYOMI_RUNTIME_CONTEXT','CLOUD_LEARN_RUNTIME_CONTEXT') 'outer').ToLowerInvariant()
if ($RuntimeContext -ne 'inner') { $RuntimeContext = 'outer' }
$ApplianceName = Get-EnvAny @('VYOMI_APPLIANCE_NAME','CLOUD_LEARN_APPLIANCE_NAME') 'cloudlearn-appliance'
$VyomiHome = Join-Path $env:USERPROFILE '.vyomi'
$ApplianceDir = Get-EnvAny @('VYOMI_APPLIANCE_DIR','CLOUD_LEARN_APPLIANCE_DIR') (Join-Path (Join-Path $VyomiHome 'appliance') $ApplianceName)
$ApplianceImage = Get-EnvAny @('VYOMI_APPLIANCE_IMAGE','CLOUD_LEARN_APPLIANCE_IMAGE') '24.04'
$_recSizing = Get-RecommendedSizing
$ApplianceCpus = [int](Get-EnvAny @('VYOMI_APPLIANCE_CPUS','CLOUD_LEARN_APPLIANCE_CPUS') ([string]$_recSizing.Cpus))
$ApplianceMemory = Get-EnvAny @('VYOMI_APPLIANCE_MEMORY','CLOUD_LEARN_APPLIANCE_MEMORY') ("{0}G" -f $_recSizing.MemGb)
$ApplianceDisk = Get-EnvAny @('VYOMI_APPLIANCE_DISK','CLOUD_LEARN_APPLIANCE_DISK') ("{0}G" -f $_recSizing.DiskGb)
$ApplianceWorkspace = Get-EnvAny @('VYOMI_APPLIANCE_WORKSPACE','CLOUD_LEARN_APPLIANCE_WORKSPACE') '/workspace/cloud-learn'
$HostSizingFileName = 'host-sizing-report.json'
$BridgePorts = @(9000, 9443)

$env:CLOUDLEARN_DISTRIBUTION_MODE = $DistributionMode
$env:CLOUD_LEARN_RUNTIME_CONTEXT = $RuntimeContext
$env:VYOMI_RUNTIME_CONTEXT = $RuntimeContext

if ($RuntimeContext -eq 'inner' -and [string]::IsNullOrWhiteSpace((Get-EnvAny @('VYOMI_COMPOSE_FILE','CLOUD_LEARN_COMPOSE_FILE')))) {
  $ComposeFile = Join-Path $RootDir 'docker-compose.appliance.yml'
}

# -- Progress + logging ---------------------------------------------------
$script:LogFile = $null
function Initialize-Log {
  try {
    $logDir = Join-Path $VyomiHome 'logs'
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
    $stamp = [DateTime]::Now.ToString('yyyyMMdd-HHmmss')
    $script:LogFile = Join-Path $logDir "up-$stamp.log"
    # Keep only the most recent 10 logs.
    Get-ChildItem -Path $logDir -Filter 'up-*.log' -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending | Select-Object -Skip 10 |
      Remove-Item -Force -ErrorAction SilentlyContinue
  } catch { }
}

function Write-ProgressLine {
  param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Message)
  Write-Output $Message
  if ($script:LogFile) {
    try { Add-Content -Path $script:LogFile -Value ("[{0}] {1}" -f ([DateTime]::Now.ToString('HH:mm:ss')), $Message) } catch { }
  }
}

# -- Multipass discovery + auto-install (winget) --------------------------
function Get-MultipassCommand {
  if (Get-Command multipass -ErrorAction SilentlyContinue) { return 'multipass' }
  throw 'Multipass is required for appliance mode. Run `vyomi up` again after installing it, or install manually: winget install Canonical.Multipass'
}

function Install-Multipass {
  if (Get-Command multipass -ErrorAction SilentlyContinue) { return $true }
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-ProgressLine '==> Multipass not found and winget is unavailable. Install Multipass from https://multipass.run/install then re-run `vyomi up`.'
    return $false
  }
  Write-ProgressLine '==> Multipass not found - installing via winget (a UAC prompt will appear)...'
  try {
    & winget install --id Canonical.Multipass --accept-package-agreements --accept-source-agreements --disable-interactivity
  } catch {
    Write-ProgressLine '==> winget install failed. Install Multipass manually from https://multipass.run/install'
    return $false
  }
  # multipass.exe lands on PATH only in a NEW shell; add the default dir for this session.
  $mpDir = Join-Path $env:ProgramFiles 'Multipass\bin'
  if ((Test-Path $mpDir) -and ($env:Path -notlike "*$mpDir*")) { $env:Path = "$mpDir;$env:Path" }
  if (Get-Command multipass -ErrorAction SilentlyContinue) { return $true }
  Write-ProgressLine '==> Multipass installed. Open a NEW terminal and run `vyomi up` again so multipass.exe is on PATH.'
  return $false
}

function Start-MultipassHost {
  try {
    Get-Service -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match 'multipass' -or $_.DisplayName -match 'Multipass' } |
      ForEach-Object { if ($_.Status -ne 'Running') { Start-Service -InputObject $_ -ErrorAction SilentlyContinue } }
  } catch { }
}

function Test-MultipassReady {
  param([int]$TimeoutSeconds = 12)
  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  $attempted = $false
  while ([DateTime]::UtcNow -lt $deadline) {
    try {
      $compose = Get-MultipassCommand
      & $compose list --format json | Out-Null
      return $true
    } catch {
      if (-not $attempted) {
        Write-ProgressLine '==> Multipass: daemon/socket not reachable, attempting host auto-start'
        Start-MultipassHost
        $attempted = $true
      }
      Start-Sleep -Seconds 3
    }
  }
  return $false
}

# -- Appliance manifest + host sizing -------------------------------------
function Write-ApplianceManifest {
  if (-not (Test-Path $ApplianceDir)) { New-Item -ItemType Directory -Force -Path $ApplianceDir | Out-Null }
  $payload = [ordered]@{
    name = $ApplianceName; image = $ApplianceImage; cpus = $ApplianceCpus
    memory = $ApplianceMemory; disk = $ApplianceDisk; workspace = $ApplianceWorkspace
    host_os = $ParentOs; distribution_mode = $DistributionMode
    created_at = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.000Z')
  }
  Set-Content -Path (Join-Path $ApplianceDir 'appliance-bootstrap.json') -Value (($payload | ConvertTo-Json -Depth 6) + [Environment]::NewLine) -Encoding utf8
}

function Get-ApplianceSshPublicKey {
  $privateKey = Join-Path $env:USERPROFILE '.ssh/cloudlearn_multipass_ed25519'
  $publicKey = "$privateKey.pub"
  if (-not (Test-Path $privateKey) -or -not (Test-Path $publicKey)) {
    $sshDir = Split-Path -Parent $privateKey
    if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory -Force -Path $sshDir | Out-Null }
    try { & ssh-keygen -t ed25519 -N '' -f $privateKey -C 'vyomi' | Out-Null } catch { }
  }
  if (Test-Path $publicKey) { return (Get-Content -Path $publicKey -Raw).Trim() }
  return ''
}

function Write-ApplianceHostSizing {
  if (-not (Test-Path $ApplianceDir)) { New-Item -ItemType Directory -Force -Path $ApplianceDir | Out-Null }
  $driveRoot = (Get-Item -LiteralPath $RootDir).PSDrive.Root
  $driveInfo = [System.IO.DriveInfo]::new($driveRoot)
  $cpuCount = [Environment]::ProcessorCount
  $memoryBytes = 0
  try { $memoryBytes = [int64]((Get-CimInstance -ClassName Win32_ComputerSystem).TotalPhysicalMemory) } catch { $memoryBytes = 0 }
  $memoryGib = [Math]::Round($memoryBytes / 1GB, 1)
  $totalBytes = [int64]$driveInfo.TotalSize
  $freeBytes = [int64]$driveInfo.AvailableFreeSpace
  $totalGib = [Math]::Round($totalBytes / 1GB, 1)
  $freeGib = [Math]::Round($freeBytes / 1GB, 1)
  if ($memoryGib -le 4) { $applianceMemory = 2; $applianceDisk = 24 }
  elseif ($memoryGib -le 8) { $applianceMemory = 4; $applianceDisk = 32 }
  elseif ($memoryGib -le 16) { $applianceMemory = 8; $applianceDisk = 32 }
  elseif ($memoryGib -le 32) { $applianceMemory = 12; $applianceDisk = 48 }
  elseif ($memoryGib -le 64) { $applianceMemory = 16; $applianceDisk = 64 }
  else {
    $applianceMemory = [Math]::Min(24, [Math]::Max(16, [int][Math]::Round($memoryGib * 0.25)))
    $applianceDisk = [Math]::Min(96, [Math]::Max(64, [int][Math]::Round($totalGib * 0.12)))
  }
  $applianceCpus = [Math]::Max(1, [Math]::Min([Math]::Max($cpuCount - 1, 1), [int][Math]::Round($applianceMemory / 2)))
  $applianceDisk = [int][Math]::Min([Math]::Max($applianceDisk, 24), [Math]::Max(24, [int][Math]::Round($freeGib * 0.25)))
  $reserve = if ($memoryGib -le 8) { 1.5 } elseif ($memoryGib -le 16) { 2.0 } elseif ($memoryGib -le 32) { 2.5 } else { 3.0 }
  $available = [Math]::Max(0.0, [double]$applianceMemory - $reserve)
  $networkInterfaces = @([System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | Where-Object { $_.Name -and $_.Name.Trim() -ne '' } | ForEach-Object { $_.Name })
  $payload = [ordered]@{
    source = 'launcher'; host_os = $ParentOs; cpu_count = $cpuCount
    memory_bytes = $memoryBytes; memory_gib = $memoryGib
    disk_total_bytes = $totalBytes; disk_used_bytes = ($totalBytes - $freeBytes); disk_free_bytes = $freeBytes
    disk_total_gib = $totalGib; disk_free_gib = $freeGib
    network_interfaces = $networkInterfaces; network_interface_count = $networkInterfaces.Count
    recommended = [ordered]@{
      appliance = [ordered]@{ vcpus = $applianceCpus; memory_gib = $applianceMemory; disk_gib = $applianceDisk }
      lxd_budget = [ordered]@{
        platform_reserve_gib = $reserve
        small_instances = [int]([Math]::Floor($available / 0.5))
        medium_instances = [int]([Math]::Floor($available / 1.0))
        heavy_instances = [int]([Math]::Floor($available / 2.0))
      }
    }
    warnings = @()
    checked_at = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.000Z')
  }
  if ($cpuCount -lt 4 -or $memoryGib -lt 8) {
    $payload.warnings = @('This host is small for a full appliance. Keep the VM at minimum size and avoid heavy sandboxes.')
  }
  Set-Content -Path (Join-Path $ApplianceDir $HostSizingFileName) -Value (($payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine) -Encoding utf8
}

# -- cloud-init (with mDNS, matching bash) --------------------------------
function Write-ApplianceCloudInit {
  if (-not (Test-Path $ApplianceDir)) { New-Item -ItemType Directory -Force -Path $ApplianceDir | Out-Null }
  $publicKey = Get-ApplianceSshPublicKey
  $sshKeys = ''
  if (-not [string]::IsNullOrWhiteSpace($publicKey)) { $sshKeys = "ssh_authorized_keys:`n  - $publicKey`n" }
  @"
#cloud-config
package_update: true
package_upgrade: true
$sshKeys
write_files:
  # Pull Docker Hub images through Google's mirror (far more reliable than the
  # direct registry-1.docker.io path that flakes with TLS handshake timeouts),
  # one blob at a time with built-in retries - so the ~couple-GB first-boot pull
  # survives slow/flaky links.
  - path: /etc/docker/daemon.json
    permissions: '0644'
    content: |
      {"registry-mirrors": ["https://mirror.gcr.io"], "max-concurrent-downloads": 1, "max-download-attempts": 5}
packages:
  - python3
  - python3-pip
  - curl
  - ca-certificates
  - docker.io
  - docker-compose-v2
  - avahi-daemon
  - libnss-mdns
runcmd:
  - [ bash, -lc, "systemctl enable docker && systemctl restart docker" ]
  - [ bash, -lc, "usermod -aG docker ubuntu || true" ]
  - [ bash, -lc, "snap install lxd || true" ]
  - [ bash, -lc, "usermod -aG lxd ubuntu || true" ]
  - [ bash, -lc, "cat >/tmp/cloudlearn-lxd-preseed.yaml <<'EOF'\nconfig: {}\nnetworks:\n- name: lxdbr0\n  type: bridge\n  config:\n    ipv4.address: auto\n    ipv4.nat: \"true\"\n    ipv6.address: auto\n    ipv6.nat: \"true\"\nstorage_pools:\n- name: default\n  driver: dir\nprofiles:\n- name: default\n  description: Default LXD profile\n  config: {}\n  devices:\n    root:\n      type: disk\n      pool: default\n      path: /\n    eth0:\n      type: nic\n      network: lxdbr0\n      name: eth0\nEOF\nlxd init --preseed < /tmp/cloudlearn-lxd-preseed.yaml || true" ]
  - [ bash, -lc, "hostnamectl set-hostname vyomi || true" ]
  - [ bash, -lc, "sed -i 's/^hosts:.*/hosts: files mdns4_minimal [NOTFOUND=return] dns mdns4/' /etc/nsswitch.conf || true" ]
  - [ bash, -lc, "systemctl enable --now avahi-daemon || true" ]
  - [ bash, -lc, "mkdir -p ${ApplianceWorkspace}" ]
  - [ bash, -lc, "mkdir -p /var/lib/cloudlearn/deployments" ]
"@ | Set-Content -Path (Join-Path $ApplianceDir 'cloud-init.yaml') -Encoding utf8
}

# -- VM state helpers -----------------------------------------------------
function Get-ApplianceRecord {
  try {
    $compose = Get-MultipassCommand
    $payload = & $compose list --format json | ConvertFrom-Json
    if ($payload -and $payload.PSObject.Properties.Name -contains 'list') {
      foreach ($inst in $payload.list) { if ($inst.name -eq $ApplianceName) { return $inst } }
    }
  } catch { }
  return $null
}

function Test-ApplianceExists { return ($null -ne (Get-ApplianceRecord)) }

function Get-ApplianceState {
  $rec = Get-ApplianceRecord
  if ($null -eq $rec) { return '' }
  $s = if ($rec.PSObject.Properties.Name -contains 'state') { $rec.state } else { $rec.status }
  if ($null -eq $s) { return '' }
  return ([string]$s).ToLowerInvariant()
}

function Get-ApplianceIp {
  $rec = Get-ApplianceRecord
  if ($null -eq $rec) { return '' }
  if ($rec.PSObject.Properties.Name -contains 'ipv4') {
    foreach ($ip in @($rec.ipv4)) {
      # Prefer a routable 192.168.x.x address (multipass host network).
      if ($ip -match '^\d+\.\d+\.\d+\.\d+$' -and $ip -notmatch '^(172\.1[7-9]\.|172\.2[0-9]\.|172\.3[0-1]\.|10\.)') { return $ip }
    }
    foreach ($ip in @($rec.ipv4)) { if ($ip -match '^\d+\.\d+\.\d+\.\d+$') { return $ip } }
  }
  return ''
}

# -- Workspace sync (tar + transfer; NOT multipass mount) -----------------
function Sync-WorkspaceIntoVm {
  $compose = Get-MultipassCommand
  Write-ProgressLine '==> Appliance: syncing workspace into VM (tar + transfer)'
  $items = @('Dockerfile','docker-compose.appliance.yml','docker-compose.yml','VERSION','requirements.txt',
             'server.py','setup_cython.py','.env.example','core','providers','routes','static','packs','scripts','packaging',
             'cloudsim-backbone') |
           Where-Object { Test-Path (Join-Path $RootDir $_) }
  $tarball = Join-Path $env:TEMP ('vyomi-src-' + [Guid]::NewGuid().ToString('N') + '.tgz')
  $tarArgs = @('-czf', $tarball, '-C', $RootDir,
               '--exclude=__pycache__', '--exclude=*.pyc', '--exclude=node_modules',
               '--exclude=.git', '--exclude=target', '--exclude=dist') + $items
  & tar.exe @tarArgs
  if ($LASTEXITCODE -ne 0) { throw 'Failed to create source tarball (tar.exe). Windows 10 1803+ ships tar; ensure it is on PATH.' }
  try {
    & $compose transfer $tarball "$ApplianceName`:/tmp/vyomi-src.tgz"
    & $compose exec $ApplianceName -- /bin/bash -lc "sudo mkdir -p '$ApplianceWorkspace' && sudo tar xzf /tmp/vyomi-src.tgz -C '$ApplianceWorkspace' && sudo chown -R ubuntu:ubuntu '$ApplianceWorkspace' && rm -f /tmp/vyomi-src.tgz"
  } finally {
    Remove-Item -Path $tarball -Force -ErrorAction SilentlyContinue
  }
}

function Sync-HostSizingIntoVm {
  $compose = Get-MultipassCommand
  $hostFile = Join-Path $ApplianceDir $HostSizingFileName
  if (-not (Test-Path $hostFile)) { return }
  Write-ProgressLine '==> Appliance: syncing host sizing into VM-local storage'
  & $compose transfer $hostFile "$ApplianceName`:/tmp/$HostSizingFileName"
  & $compose exec $ApplianceName -- /bin/bash -lc "sudo mkdir -p /var/lib/cloudlearn && sudo install -m 644 /tmp/$HostSizingFileName /var/lib/cloudlearn/$HostSizingFileName && rm -f /tmp/$HostSizingFileName"
}

# -- Runtime bridge (transfer + systemd unit, matching bash) --------------
function Install-RuntimeBridge {
  $compose = Get-MultipassCommand
  $bridgeSrc = Join-Path $RootDir 'core/runtime_bridge.py'
  if (-not (Test-Path $bridgeSrc)) { throw "runtime bridge source not found at $bridgeSrc" }
  Write-ProgressLine '==> Appliance: installing VM-local runtime bridge (systemd)'
  & $compose transfer $bridgeSrc "$ApplianceName`:/tmp/runtime_bridge.py"
  $unit = @'
[Unit]
Description=Vyomi runtime bridge
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 /var/lib/cloudlearn/runtime_bridge.py --host 0.0.0.0 --port 9171
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
'@
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($unit))
  $remote = "set -e; sudo mkdir -p /var/lib/cloudlearn; sudo install -m 644 /tmp/runtime_bridge.py /var/lib/cloudlearn/runtime_bridge.py; rm -f /tmp/runtime_bridge.py; echo $b64 | base64 -d | sudo tee /etc/systemd/system/cloudlearn-runtime-bridge.service >/dev/null; sudo systemctl daemon-reload; sudo systemctl enable --now cloudlearn-runtime-bridge.service; for i in `$(seq 1 30); do curl -fsS http://127.0.0.1:9171/health >/dev/null 2>&1 && exit 0; sleep 1; done; echo 'runtime bridge failed to start' >&2; exit 1"
  & $compose exec $ApplianceName -- /bin/bash -lc $remote
}

# -- Launch / boot the VM -------------------------------------------------
function Start-ApplianceVm {
  Write-ApplianceManifest
  Write-ApplianceHostSizing
  Write-ApplianceCloudInit
  $compose = Get-MultipassCommand
  if (-not (Test-MultipassReady)) {
    throw 'Multipass is installed, but the daemon/socket is not reachable. Open or restart Multipass on the host and retry.'
  }
  Write-ProgressLine '==> [1/6] Checking appliance VM state'
  $exists = Test-ApplianceExists
  $state = Get-ApplianceState
  if (-not $exists) {
    Write-ProgressLine ("==> [2/6] Launching VM {0}: {1} RAM / {2} CPU / {3} disk (cold start 3-5 min; host kept lean to avoid freezes)" -f $ApplianceName, $ApplianceMemory, $ApplianceCpus, $ApplianceDisk)
    & $compose launch $ApplianceImage --name $ApplianceName --cpus $ApplianceCpus --memory $ApplianceMemory --disk $ApplianceDisk --timeout 900 --cloud-init (Join-Path $ApplianceDir 'cloud-init.yaml')
  } elseif ($state -eq 'running') {
    Write-ProgressLine '==> [2/6] Existing VM detected (running)'
  } elseif ($state -eq 'stopped' -or $state -eq 'suspended') {
    Write-ProgressLine ("==> [2/6] Existing VM detected ({0}), starting it" -f $state)
    & $compose start $ApplianceName
  } else {
    Write-ProgressLine ("==> [2/6] Existing VM detected ({0}), continuing" -f ($(if ([string]::IsNullOrWhiteSpace($state)) { 'unknown' } else { $state })))
  }
  Write-ProgressLine '==> [3/6] Waiting for cloud-init'
  & $compose exec $ApplianceName -- /bin/bash -lc "cloud-init status --wait >/dev/null 2>&1 || true" | Out-Null
  Sync-WorkspaceIntoVm
  Sync-HostSizingIntoVm
}

function Invoke-ApplianceLauncher {
  $compose = Get-MultipassCommand
  Write-ProgressLine '==> [5/6] Starting the CloudLearn stack inside the appliance'
  & $compose exec $ApplianceName -- /bin/bash -lc "sudo mkdir -p /var/lib/cloudlearn/deployments && cd '$ApplianceWorkspace' && CLOUD_LEARN_HOME='$ApplianceWorkspace' CLOUD_LEARN_RUNTIME_CONTEXT=inner CLOUD_LEARN_DISTRIBUTION_MODE=appliance CLOUD_LEARN_COMPOSE_FILE='$ApplianceWorkspace/docker-compose.appliance.yml' bash ./scripts/cloud-learn up --detach"
}

# -- Health check (direct bridged IP) -------------------------------------
function Test-ApplianceHealth {
  param([int]$TimeoutSeconds = 0)
  if ($TimeoutSeconds -le 0) {
    $TimeoutSeconds = [int](Get-EnvAny @('VYOMI_HEALTH_TIMEOUT','CLOUD_LEARN_HEALTH_TIMEOUT') '600')
  }
  $vmIp = Get-ApplianceIp
  if ([string]::IsNullOrWhiteSpace($vmIp)) { throw 'Could not resolve the appliance VM IP for health checks.' }
  Write-ProgressLine ("==> [6/6] Waiting for the simulator at {0} (first boot pulls ~3.5GB - can take 10-20 min on a slow VM)" -f $vmIp)
  $waited = 0
  while ($waited -lt $TimeoutSeconds) {
    # The simulator (port 9000) is what serves the console; the runtime
    # bridge (9171) is optional, so don't block on it.
    try { Invoke-WebRequest -Uri ("http://{0}:9000/healthz" -f $vmIp) -TimeoutSec 3 -UseBasicParsing | Out-Null; return $vmIp } catch { }
    Start-Sleep -Seconds 5
    $waited += 5
    if ($waited % 30 -eq 0) { Write-ProgressLine ("    ... still starting ({0}s) - pulling/booting the stack inside the VM" -f $waited) }
  }
  # Don't fail hard: on a slow box the stack frequently comes up AFTER the
  # wait expires. Warn, but keep going so the bridge + URL still get set up.
  Write-ProgressLine ''
  Write-ProgressLine '==> Simulator not reachable yet - it is still starting inside the VM (slow first boot / image pull).'
  Write-ProgressLine ("    Check progress: multipass exec {0} -- sudo docker ps" -f $ApplianceName)
  Write-ProgressLine '    The access URL below will start working once it finishes.'
  return $vmIp
}

# -- localhost bridge (netsh portproxy) + browser -------------------------
function Start-LocalhostBridge {
  param([string]$VmIp)
  if ([string]::IsNullOrWhiteSpace($VmIp)) { return }
  if (-not (Get-Command netsh -ErrorAction SilentlyContinue)) { return }
  foreach ($port in $BridgePorts) {
    try {
      & netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=$port 2>$null | Out-Null
      & netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=$port connectaddress=$VmIp connectport=$port | Out-Null
    } catch {
      Write-ProgressLine ("==> Note: could not bridge localhost:{0} (needs an elevated shell). Use http://{1}:{0}/ instead." -f $port, $VmIp)
    }
  }
}

function Show-UrlBanner {
  param([string]$VmIp)
  $url = "http://$VmIp:9000/"
  # Prefer localhost if the portproxy bridge answers.
  try { Invoke-WebRequest -Uri 'http://127.0.0.1:9000/healthz' -TimeoutSec 2 -UseBasicParsing | Out-Null; $url = 'http://localhost:9000/' } catch { }
  Write-ProgressLine ''
  Write-ProgressLine '  ============================================================'
  Write-ProgressLine '   Vyomi appliance is READY'
  Write-ProgressLine ("   Console : {0}" -f $url)
  Write-ProgressLine ("   Direct  : http://{0}:9000/   (VM IP, no bridge needed)" -f $VmIp)
  Write-ProgressLine '  ============================================================'
  Write-ProgressLine ''
  if ((Get-EnvAny @('VYOMI_NO_OPEN','CLOUD_LEARN_NO_OPEN')) -ne '1') {
    try { Start-Process $url | Out-Null } catch { }
  }
}

# -- Upgrade --------------------------------------------------------------
function Invoke-Upgrade {
  $compose = Get-MultipassCommand
  if (-not (Test-ApplianceExists)) { throw "Appliance VM '$ApplianceName' does not exist. Run `vyomi up` first." }
  $vmIp = Get-ApplianceIp
  Write-ProgressLine '==> Checking for updates...'
  $current = ''; $latest = ''
  try {
    $resp = Invoke-WebRequest -Uri ("http://{0}:9000/api/runtime/update-check" -f $vmIp) -TimeoutSec 5 -UseBasicParsing
    $j = $resp.Content | ConvertFrom-Json
    $current = [string]$j.current; $latest = [string]$j.latest
  } catch {
    throw 'Could not reach the appliance update-check endpoint. Is the appliance running (`vyomi status`)?'
  }
  if ([string]::IsNullOrWhiteSpace($latest) -or $latest -eq $current) {
    Write-ProgressLine ("==> Already up to date (v{0})." -f $current); return
  }
  Write-ProgressLine ("==> Pulling vyomi/appliance:{0} inside {1}..." -f $latest, $ApplianceName)
  & $compose exec $ApplianceName -- /bin/bash -lc "sudo docker pull vyomi/appliance:$latest"
  Write-ProgressLine '==> Recreating the simulator container with the new image...'
  & $compose exec $ApplianceName -- /bin/bash -lc "cd '$ApplianceWorkspace' && CLOUDLEARN_SIMULATOR_IMAGE=vyomi/appliance:$latest docker compose -f docker-compose.appliance.yml up -d --force-recreate simulator"
  Test-ApplianceHealth | Out-Null
  Write-ProgressLine ("==> Vyomi appliance is now on v{0}" -f $latest)
}

# -- Inner-context compose helpers (unchanged behavior) -------------------
function Get-ComposeBackend {
  if (Get-Command docker -ErrorAction SilentlyContinue) {
    try { & docker compose version | Out-Null; return @{ File = 'docker'; Args = @('compose') } } catch { }
  }
  if (Get-Command docker-compose -ErrorAction SilentlyContinue) { return @{ File = 'docker-compose'; Args = @() } }
  throw 'docker compose is not available'
}

function Test-ComposeEngine { try { & docker info | Out-Null; return $true } catch { return $false } }

function Wait-ComposeBackendReady {
  param([int]$TimeoutSeconds = 180)
  $waited = 0
  while ($waited -lt $TimeoutSeconds) {
    try { & docker compose version | Out-Null; & docker info | Out-Null; return $true } catch { }
    try { & docker-compose version | Out-Null; & docker info | Out-Null; return $true } catch { }
    Start-Sleep -Seconds 2; $waited += 2
  }
  throw 'docker compose is not available inside the appliance VM yet'
}

function Invoke-Compose {
  param([Parameter(Mandatory = $true)][string]$Verb, [string[]]$ExtraArgs = @())
  Wait-ComposeBackendReady | Out-Null
  $backend = Get-ComposeBackend
  if ($backend.File -eq 'docker') {
    & docker compose --project-name $ProjectName --project-directory $RootDir -f $ComposeFile $Verb @ExtraArgs
    return
  }
  & docker-compose --project-name $ProjectName --project-directory $RootDir -f $ComposeFile $Verb @ExtraArgs
}

function Write-Doctor {
  Write-Output "vyomi root: $RootDir"
  Write-Output "compose file: $ComposeFile"
  Write-Output "runtime context: $RuntimeContext"
  if ($RuntimeContext -eq 'inner') {
    Write-Output ("docker: " + ($(if (Get-Command docker -ErrorAction SilentlyContinue) { 'available' } else { 'missing' })))
    Write-Output ("engine: " + ($(if (Test-ComposeEngine) { 'reachable' } else { 'unreachable' })))
    Write-Output 'mode: appliance inner stack'
  } else {
    Write-Output ("multipass: " + ($(if (Get-Command multipass -ErrorAction SilentlyContinue) { 'available' } else { 'missing' })))
    Write-Output ("appliance VM: " + ($(if (Test-ApplianceExists) { Get-ApplianceState } else { 'absent' })))
    Write-Output 'mode: appliance launcher'
  }
}

function Show-Usage {
  @'
vyomi - local multi-cloud simulator launcher (Windows)

Usage:
  vyomi up          Boot the appliance VM and start the simulator
  vyomi down        Stop the appliance VM
  vyomi stop        Alias for down
  vyomi force-stop  Force-stop the VM
  vyomi restart     Restart the VM + stack
  vyomi status      Show appliance VM info
  vyomi upgrade     Pull the latest appliance image and recreate the simulator
  vyomi doctor      Print diagnostics
  vyomi help        This help

Environment (VYOMI_* preferred; CLOUD_LEARN_* still honored):
  VYOMI_HOME              Root dir containing the vyomi sources
  VYOMI_APPLIANCE_NAME    Multipass VM name (default: cloudlearn-appliance)
  VYOMI_APPLIANCE_CPUS/MEMORY/DISK   VM sizing overrides
  VYOMI_NO_OPEN=1         Don't auto-open the browser
'@ | Write-Output
}

# -- Dispatch -------------------------------------------------------------
$cmd = if ($RemainingArgs.Count -gt 0) { $RemainingArgs[0] } else { 'help' }
$cmdArgs = if ($RemainingArgs.Count -gt 1) { $RemainingArgs[1..($RemainingArgs.Count - 1)] } else { @() }

if ($RuntimeContext -eq 'inner') {
  switch ($cmd) {
    'up' { Invoke-Compose -Verb 'up' -ExtraArgs (@('--build', '--force-recreate') + $cmdArgs) }
    'down' { Invoke-Compose -Verb 'down' -ExtraArgs $cmdArgs }
    'restart' { Invoke-Compose -Verb 'restart' -ExtraArgs $cmdArgs }
    'status' { Invoke-Compose -Verb 'ps' -ExtraArgs $cmdArgs }
    'doctor' { Write-Doctor }
    'help' { Show-Usage }
    default { Write-Error "Unknown inner command: $cmd"; Show-Usage; exit 2 }
  }
} else {
  switch ($cmd) {
    'up' {
      Initialize-Log
      if (-not (Get-Command multipass -ErrorAction SilentlyContinue)) {
        if (-not (Install-Multipass)) { exit 1 }
      }
      Start-ApplianceVm
      Write-ProgressLine '==> [4/6] Installing the runtime bridge'
      Install-RuntimeBridge
      Invoke-ApplianceLauncher
      $vmIp = Test-ApplianceHealth
      Start-LocalhostBridge -VmIp $vmIp
      Show-UrlBanner -VmIp $vmIp
    }
    'down' { $compose = Get-MultipassCommand; & $compose stop $ApplianceName | Out-Null }
    'stop' { $compose = Get-MultipassCommand; & $compose stop $ApplianceName | Out-Null }
    'force-stop' { $compose = Get-MultipassCommand; & $compose stop --force $ApplianceName | Out-Null }
    'kill' { $compose = Get-MultipassCommand; & $compose stop --force $ApplianceName | Out-Null }
    'restart' {
      Initialize-Log
      $compose = Get-MultipassCommand
      & $compose restart $ApplianceName | Out-Null
      & $compose exec $ApplianceName -- /bin/bash -lc "cloud-init status --wait >/dev/null 2>&1 || true" | Out-Null
      Install-RuntimeBridge
      Invoke-ApplianceLauncher
      $vmIp = Test-ApplianceHealth
      Start-LocalhostBridge -VmIp $vmIp
      Show-UrlBanner -VmIp $vmIp
    }
    'status' { $compose = Get-MultipassCommand; & $compose info $ApplianceName }
    'upgrade' { Initialize-Log; Invoke-Upgrade }
    'doctor' { Write-Doctor }
    'help' { Show-Usage }
    default { Write-Error "Unknown command: $cmd"; Show-Usage; exit 2 }
  }
}
