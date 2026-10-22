param(
    [string]$Run = 'BaseStone_' + (Get-Date -Format 'yyyyMMdd_HHmmss'),
    [switch]$HideUI,
    [switch]$RockTower,
    [ValidateRange(-1,1)][int]$Defender = -1,
    [switch]$CycleCapture,
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
$root = 'F:\code\CivWar'
if ($Run -notmatch '^[A-Za-z][A-Za-z0-9_]*$') { throw 'Unsafe run name' }
if ($Defender -ge 0 -and -not $RockTower) { throw 'Defender scenario requires explicit RockTower fixture' }
if ($CycleCapture -and $Defender -lt 0) { throw 'Cycle capture requires a defender scenario' }
$output = Join-Path $root "RawAssets\Art\Tripo_v01\reviews\$Run"
if (Test-Path -LiteralPath $output) { throw 'Run directory already exists; preserve earlier evidence' }
$configPath = Join-Path $root 'Content\Data\BaseArtPilot.json'
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $config.enabled -or -not $config.ue_structural_approved -or -not $config.placement_approved_for_pilot -or $config.asset_id -ne 'Base_Stone') { throw 'Missing base pilot approval' }
if ($config.static_mesh -notmatch '^/Game/ArtPilot/tripo_base_stone_pbr_v01/Base_Stone/h[0-9a-f]{12}/Base_Stone\.Base_Stone$') { throw 'Unexpected base package' }
$mapping = 'RawAssets/Art/Tripo_v01/reviews/environment_inputs_20261020/six_asset_game_review.json'
$mappingPath = Join-Path $root $mapping
$permanentPath = Join-Path $root 'Content\Data\EnvironmentArt.json'
$configHash = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash.ToLowerInvariant()
$mappingHash = (Get-FileHash -LiteralPath $mappingPath -Algorithm SHA256).Hash.ToLowerInvariant()
$permanentHash = (Get-FileHash -LiteralPath $permanentPath -Algorithm SHA256).Hash.ToLowerInvariant()
$mappingData = Get-Content -LiteralPath $mappingPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $mappingData.partial_review_only -or $mappingData.assets.Env_GrassClump -or $mappingData.permanent_runtime_mapping_sha256 -ne $permanentHash) { throw 'Invalid six-environment temporary map' }
$logPath = Join-Path $output 'standalone.log'
$arguments = @(
    '"F:/code/CivWar/CivWar.uproject"', '-game', '-RenderOffscreen', '-unattended', '-nosplash', '-nop4', '-nosound',
    '-windowed', '-ForceRes', '-ResX=1600', '-ResY=900', '-noshaderworker', '-DDC=InstalledNoZenLocalFallback',
    '-cwsingle=0', '-cwautoready', '-cwautoplay', '-cwstoneaxepilot', '-cwbasestonepilot', '-cwartreview', '-cwbaseartreview',
    '-cwperf', '-cwquitafter=80', "-cwshotprefix=$Run", "-cwartenvironment=$mapping",
    '-ExecCmds="t.MaxFPS 20"', ('-abslog="' + $logPath + '"')
) -join ' '
if ($HideUI) { $arguments += ' -cwbasearthideui' }
if ($CycleCapture) { $arguments += ' -cwrocktowercyclecapture' }
if ($RockTower) {
    $turretPath = Join-Path $root 'Content/Data/TurretArtPilot.json'
    $turret = Get-Content -LiteralPath $turretPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $turret.enabled -or -not $turret.ue_structural_approved -or -not $turret.assembly_approved_for_pilot -or $turret.asset_id -ne 'Turret_RockTower') { throw 'Missing actual RockTower assembly pilot approval' }
    $turretHash = (Get-FileHash -LiteralPath $turretPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $arguments += ' -cwrocktowerpilot -cwrocktowerfixture'
    if ($Defender -ge 0) {
        $arguments += " -cwrocktowerdefender=$Defender"
        $arguments = $arguments.Replace('-cwquitafter=80', '-cwquitafter=110')
        if ($Defender -eq 0) { $arguments = $arguments.Replace(' -cwautoplay', '') }
    }
}
if (-not $Execute) { @{mode='dry_run'; arguments=$arguments; config_sha256=$configHash} | ConvertTo-Json; return }
if (@(Get-Process blender,UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue).Count -ne 0) { throw 'Heavy slot is occupied' }
New-Item -ItemType Directory -Path $output | Out-Null
$started = [DateTime]::UtcNow
$process = Start-Process -FilePath 'G:/epic/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe' -ArgumentList $arguments -WindowStyle Hidden -PassThru
$process.PriorityClass = 'BelowNormal'
$process.ProcessorAffinity = [IntPtr]15
Write-Output "Base review PID=$($process.Id)"
$timedOut = -not $process.WaitForExit(180000)
if ($timedOut) { Stop-Process -Id $process.Id; $process.WaitForExit() }
$logText = if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath -Raw -Encoding UTF8 } else { '' }
$screenshots = @()
$failures = @()
foreach ($team in @(0,1)) {
    foreach ($distance in @(1300,2300,3400)) {
        $path = Join-Path $root "Saved/Screenshots/WindowsEditor/${Run}_team${team}_distance${distance}.png"
        if (Test-Path -LiteralPath $path) {
            $bytes = [IO.File]::ReadAllBytes($path)
            $width = $bytes[16] * 16777216 + $bytes[17] * 65536 + $bytes[18] * 256 + $bytes[19]
            $height = $bytes[20] * 16777216 + $bytes[21] * 65536 + $bytes[22] * 256 + $bytes[23]
            if ($width -ne 1600 -or $height -ne 900) { $failures += "Unexpected image size: $path" }
            $screenshots += @{path=$path; bytes=$bytes.Length; sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant(); width=$width; height=$height}
        } else { $failures += "Missing screenshot: $path" }
    }
}
$baseEvidence = @([regex]::Matches($logText, 'CIVWAR_BASE_STONE_PILOT[^\r\n]*') | ForEach-Object {$_.Value})
$cycleScreenshots = @()
if ($CycleCapture) {
    foreach ($phase in 0..5) {
        $name = "${Run}_cycle_team${Defender}_phase${phase}.png"
        $path = Join-Path $root "Saved/Screenshots/WindowsEditor/$name"
        if (-not (Test-Path -LiteralPath $path)) { $failures += "Missing cycle screenshot: $path"; continue }
        $bytes = [IO.File]::ReadAllBytes($path)
        $width = $bytes[16] * 16777216 + $bytes[17] * 65536 + $bytes[18] * 256 + $bytes[19]
        $height = $bytes[20] * 16777216 + $bytes[21] * 65536 + $bytes[22] * 256 + $bytes[23]
        if ($width -ne 1600 -or $height -ne 900) { $failures += "Invalid cycle resolution: $name" }
        if ([regex]::Matches($logText, "CIVWAR_ROCK_TOWER_IMAGE shot=$([regex]::Escape($name)) ").Count -ne 1) { $failures += "Missing or repeated actual cycle shot telemetry: $name" }
        $cycleScreenshots += @{path=$path; bytes=$bytes.Length; sha256=(Get-FileHash -LiteralPath $path).Hash.ToLowerInvariant(); width=$width; height=$height; phase=$phase}
    }
}
foreach ($team in @(0,1)) { if (-not ($baseEvidence -match "team=$team ")) { $failures += "Actual base pilot absent for team$team" } }
$teamMaterialEvidence = @([regex]::Matches($logText, 'CIVWAR_BASE_TEAM_MATERIAL[^\r\n]*') | ForEach-Object {$_.Value})
if ($config.team_material) {
    foreach ($team in @(0,1)) {
        $expected = "team=$team material=$($config.team_material) cloth_mask_only=true"
        if (-not ($teamMaterialEvidence | Where-Object { $_.Contains($expected) })) { $failures += "Actual team material absent or differs for team$team" }
    }
}
if ($process.ExitCode -ne 0 -or $timedOut) { $failures += 'Game process failed or timed out' }
$turretEvidence = @([regex]::Matches($logText, 'CIVWAR_ROCK_TOWER_[^\r\n]*') | ForEach-Object {$_.Value})
if ($RockTower) {
    foreach ($team in @(0,1)) {
        foreach ($slot in @(0,1,2)) {
            if (-not ($turretEvidence -match "PILOT team=$team slot=$slot components=5 ")) { $failures += "Missing actual turret: team$team slot$slot" }
            if (-not ($turretEvidence -match "FIXTURE team=$team slot=$slot result=0 ")) { $failures += "Fixture normal command failed: team$team slot$slot" }
        }
    }
    if ((Get-FileHash -LiteralPath $turretPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $turretHash) { $failures += 'Turret mapping changed during capture' }
}
foreach ($entry in @(@($configPath,$configHash), @($mappingPath,$mappingHash), @($permanentPath,$permanentHash))) {
    if ((Get-FileHash -LiteralPath $entry[0] -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry[1]) { $failures += "Changed mapping: $($entry[0])" }
}
$report = @{
    run=$Run; mode='single_standalone'; arguments=$arguments; hide_ui_requested=[bool]$HideUI; rock_tower_fixture=[bool]$RockTower; defender=$Defender; turret_evidence=$turretEvidence; process_id=$process.Id; exit_code=$process.ExitCode; timed_out=$timedOut
    started_at_utc=$started.ToString('o'); finished_at_utc=[DateTime]::UtcNow.ToString('o'); config_sha256=$configHash; permanent_mapping_sha256=$permanentHash
    screenshots=$screenshots; cycle_screenshots=$cycleScreenshots; cycle_capture=[bool]$CycleCapture; base_evidence=$baseEvidence; team_material_evidence=$teamMaterialEvidence; camera_evidence=@([regex]::Matches($logText,'CIVWAR_ART_REVIEW[^\r\n]*') | ForEach-Object {$_.Value})
    perf_evidence=@([regex]::Matches($logText,'CIVWAR_PERF[^\r\n]*') | ForEach-Object {$_.Value}); failures=$failures
    visual_approved=$false; production_approved=$false; scope='Controlled six-environment plus base pilot; not all-unit doorway, turret sweep, team flags, network or full-load acceptance'
}
$report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $output 'capture_report.json') -Encoding UTF8
if ($failures.Count -gt 0) { throw ($failures -join '; ') }
Write-Output ('Base capture complete; visual review required: ' + $output)
