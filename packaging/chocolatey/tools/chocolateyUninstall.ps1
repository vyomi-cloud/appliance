$ErrorActionPreference = 'Continue'

# Stop the appliance VM cleanly before uninstall
if (Get-Command cloud-learn -ErrorAction SilentlyContinue) {
  & cloud-learn down 2>&1 | Out-Null
}

$packageName = 'cloud-learn'
[array]$key = Get-UninstallRegistryKey -SoftwareName 'CloudLearn*'
if ($key.Count -eq 1) {
  $packageArgs = @{
    packageName    = $packageName
    fileType       = 'msi'
    silentArgs     = "$($key[0].PSChildName) /qn /norestart"
    validExitCodes = @(0, 1605, 1614, 1641, 3010)
  }
  Uninstall-ChocolateyPackage @packageArgs
}
