# Build a distributable Windows portable ZIP. No editor or development files are copied.
param(
    [ValidatePattern('^[0-9A-Za-z][0-9A-Za-z.-]*$')]
    [string]$Version = '0.1.0-playtest.20261022',
    [string]$EngineRoot = '',
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if ($projectRoot -match '[^\x00-\x7F]') {
    $junction = Join-Path (Split-Path -Parent $projectRoot) 'CivWar'
    $item = Get-Item -LiteralPath $junction
    if ($item.LinkType -ne 'Junction' -or [string]($item.Target | Select-Object -First 1) -ne $projectRoot) {
        throw "Expected an ASCII junction to the project at $junction. Run civwar.ps1 help first."
    }
    $projectRoot = $junction
}
$releaseRoot = Join-Path $projectRoot 'Build\Releases'
$stagingRoot = Join-Path $releaseRoot "Staging-$Version"
$name = "CivWar-$Version-Windows-x64"
$destination = Join-Path $releaseRoot $name
$zipPath = "$destination.zip"
if ((Test-Path -LiteralPath $destination) -or (Test-Path -LiteralPath $zipPath)) {
    throw "Release already exists. Use a new -Version to preserve the existing release: $destination"
}

if (-not $SkipBuild) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'Tools\civwar.ps1') package -Configuration Shipping -EngineRoot $EngineRoot -PackageDirectory $stagingRoot
    if ($LASTEXITCODE -ne 0) { throw "Packaging failed ($LASTEXITCODE)" }
}

$windows = Join-Path $stagingRoot 'Windows'
$required = @(
    'CivWar.exe',
    'CivWar\Binaries\Win64\CivWar-Win64-Shipping.exe',
    'CivWar\Binaries\Win64\vcruntime140.dll',
    'CivWar\Binaries\Win64\msvcp140.dll',
    'CivWar\Content\Paks',
    'Engine\Extras\Redist\en-us\vc_redist.x64.exe'
)
foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $windows $relative))) { throw "Missing packaged file: $relative" }
}
if (-not (Get-ChildItem -LiteralPath (Join-Path $windows 'CivWar\Content\Paks') -Filter '*.utoc')) {
    throw 'IoStore content container missing.'
}

New-Item -ItemType Directory -Path $destination -Force | Out-Null
# Copy only the runtime payload. Never include developer logs, screenshots or Saved settings.
$files = Get-ChildItem -LiteralPath $windows -File -Recurse | Where-Object {
    $relative = $_.FullName.Substring($windows.Length + 1)
    ($relative -in @('CivWar.exe', 'NOTICES.txt') -or $relative -match '^(CivWar|Engine)\\') -and
    $relative -notmatch '(^|\\)(Saved|Intermediate|Metadata)(\\|$)' -and
    $_.Extension -notin @('.pdb', '.debug', '.log', '.cpp', '.h', '.cs')
}
foreach ($file in $files) {
    $relative = $file.FullName.Substring($windows.Length + 1)
    $target = Join-Path $destination $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'Docs\PLAYTEST_README.txt') -Destination (Join-Path $destination '试玩说明.txt')
$licenses = Join-Path $destination 'Licenses'
New-Item -ItemType Directory -Path $licenses -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'Content\Licenses') -File | Copy-Item -Destination $licenses
Copy-Item -LiteralPath (Join-Path $projectRoot 'Content\Fonts\NotoSansSC-LICENSE.txt') -Destination $licenses
$launcher = "@echo off`r`ncd /d `"%~dp0`"`r`nstart `"`" `"%~dp0CivWar.exe`" %*`r`n"
[IO.File]::WriteAllText((Join-Path $destination '开始游戏.cmd'), $launcher, [Text.Encoding]::ASCII)
$manifest = [ordered]@{
    game = 'CivWar'; version = $Version; platform = 'Windows x64'; configuration = 'Shipping'
    createdUtc = [DateTime]::UtcNow.ToString('o'); executable = 'CivWar.exe'
    appLocalRuntime = $true
    files = @(Get-ChildItem -LiteralPath $destination -File -Recurse | Sort-Object FullName | ForEach-Object {
        [ordered]@{ path = $_.FullName.Substring($destination.Length + 1).Replace('\', '/'); bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destination 'release-manifest.json') -Encoding UTF8
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($destination, $zipPath, [IO.Compression.CompressionLevel]::Optimal, $true)
$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$zipPath.sha256", "$hash  $name.zip`r`n", [Text.Encoding]::ASCII)
Write-Host "Portable folder: $destination"
Write-Host "Share this ZIP: $zipPath"
Write-Host "ZIP size: $([math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 1)) MiB"
Write-Host "SHA256: $hash"
