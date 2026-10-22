param(
    [Parameter(Mandatory=$true)][string]$Run,
    [ValidateSet('default','legacy','base_camera','default_fixture')][string]$Mode = 'default',
    [ValidateRange(60,300)][int]$DurationSeconds = 210,
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
$root = 'F:/code/CivWar'
if ($Run -notmatch '^[A-Za-z][A-Za-z0-9_]*$') { throw 'Unsafe run name' }
$output = Join-Path $root "RawAssets/Art/Tripo_v01/reviews/$Run"
if (Test-Path -LiteralPath $output) { throw 'Preserve earlier evidence; choose a fresh run' }
$binary = Get-Item -LiteralPath (Join-Path $root 'Binaries/Win64/UnrealEditor-CivWar.dll')
$newer = @(Get-ChildItem -LiteralPath (Join-Path $root 'Source') -Recurse -File | Where-Object { $_.Extension -in '.cpp','.h' -and $_.LastWriteTimeUtc -gt $binary.LastWriteTimeUtc })
if ($newer.Count) { throw 'Build the changed source before running' }
$tracked = @('Content/Data/EnvironmentArt.json','Content/Data/EnvironmentArtLegacy.json','Content/Data/UnitArtPilot.json','Content/Data/BaseArtPilot.json','Content/Data/TurretArtPilot.json','Config/DefaultGame.ini','Binaries/Win64/UnrealEditor-CivWar.dll')
$hashes = @{}
foreach ($relative in $tracked) { $hashes[$relative] = (Get-FileHash -LiteralPath (Join-Path $root $relative) -Algorithm SHA256).Hash.ToLowerInvariant() }
$logPath = Join-Path $output 'game.log'
$arguments = @(
    '"F:/code/CivWar/CivWar.uproject"', '-game', '-RenderOffscreen', '-unattended', '-nosplash', '-nop4', '-nosound',
    '-windowed', '-ForceRes', '-ResX=1600', '-ResY=900', '-noshaderworker', '-DDC=InstalledNoZenLocalFallback', '-FORCELOGFLUSH',
    '-cwsingle=1', '-cwautoready', '-cwautoplay', '-cwperf', '-cwarttiming', "-cwarttimingrun=$Run", "-cwquitafter=$DurationSeconds",
    "-cwshotprefix=$Run", '-ExecCmds="t.MaxFPS 20"', ('-abslog="' + $logPath + '"')
)
if ($Mode -eq 'legacy') { $arguments += @('-cwlegacyart','-cwshots') }
elseif ($Mode -eq 'base_camera') { $arguments += @('-cwartreview','-cwbaseartreview','-cwbasearthideui') }
elseif ($Mode -eq 'default_fixture') {
    $arguments = @($arguments | Where-Object { $_ -ne '-cwautoplay' })
    $arguments += @('-cwartreview','-cwbaseartreview','-cwbasearthideui','-cwrocktowerfixture','-cwdefaultartfixture','-cwrocktowerdefender=0','-cwrocktowercyclecapture')
}
else { $arguments += @('-cwshots','-cwrocktowerfixture') }
$line = $arguments -join ' '
foreach ($forbidden in @('-cwstoneaxepilot','-cwbasestonepilot','-cwrocktowerpilot','-cwartpreview','-cwartenvironment=')) {
    if ($line.Contains($forbidden)) { throw "Asset activation override is forbidden: $forbidden" }
}
$launch = @{run=$Run; mode=$Mode; arguments=$line; protected_files=$hashes; cpu_affinity=3; fps_cap=20; asset_enablement_flags=@(); production_approved=$false}
if (-not $Execute) { $launch | ConvertTo-Json -Depth 6; return }
if (@(Get-Process UnrealEditor,UnrealEditor-Cmd,blender -ErrorAction SilentlyContinue).Count) { throw 'Heavy slot is occupied' }
New-Item -ItemType Directory -Path $output | Out-Null
$launch | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $output 'launch.json') -Encoding UTF8
$started = [DateTime]::UtcNow
$process = Start-Process -FilePath 'G:/epic/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe' -ArgumentList $line -WindowStyle Hidden -PassThru
$handle = $process.Handle
$process.PriorityClass = 'BelowNormal'
$process.ProcessorAffinity = [IntPtr]3
Write-Output "Default art review PID=$($process.Id) mode=$Mode"
$timedOut = -not $process.WaitForExit(($DurationSeconds + 120) * 1000)
if ($timedOut) { Stop-Process -Id $process.Id; $process.WaitForExit() }
$log = if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath -Raw -Encoding UTF8 } else { '' }
$failures = @()
if ($timedOut -or $process.ExitCode -ne 0) { $failures += 'UE timed out or exited unsuccessfully' }
foreach ($relative in $tracked) {
    if ((Get-FileHash -LiteralPath (Join-Path $root $relative) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hashes[$relative]) { $failures += "Changed protected file: $relative" }
}
$fatalLines = @($log -split "`n" | Where-Object { $_ -match 'Fatal error:|Assertion failed:|Ensure condition failed:' })
$failures += $fatalLines
$environment = @([regex]::Matches($log, 'CIVWAR_ENVIRONMENT_ART[^\r\n]*') | ForEach-Object {$_.Value})
$base = @([regex]::Matches($log, 'CIVWAR_BASE_STONE_PILOT[^\r\n]*') | ForEach-Object {$_.Value})
$unit = @([regex]::Matches($log, 'CIVWAR_STONEAXE_PILOT[^\r\n]*') | ForEach-Object {$_.Value})
$turret = @([regex]::Matches($log, 'CIVWAR_ROCK_TOWER_PILOT[^\r\n]*') | ForEach-Object {$_.Value})
$fixtureCount = [regex]::Matches($log, 'CIVWAR_ROCK_TOWER_FIXTURE(?: |_GOLD )').Count
if ($fixtureCount -and $Mode -ne 'default_fixture') { $failures += 'Default validation unexpectedly executed debug construction fixture' }
if ($Mode -eq 'legacy') {
    if (-not ($environment -match 'mode=legacy loaded=7 tripo=0')) { $failures += 'Legacy environment fallback was not observed' }
    if ($base.Count -or $unit.Count -or $turret.Count) { $failures += 'New model activation leaked into legacy mode' }
} else {
    if (-not ($environment -match 'mode=default loaded=7 tripo=6 grass=legacy_fallback')) { $failures += 'Default six Tripo plus legacy grass mapping was not observed' }
    foreach ($team in @(0,1)) {
        if (-not ($base -match "team=$team .*activation=default_runtime")) { $failures += "Default base missing for team $team" }
        if ($Mode -ne 'default_fixture' -and $log -notmatch "CIVWAR_STONEAXE_TEAM_MATERIAL team=$team ") { $failures += "Default StoneAxe team material missing for team $team" }
    }
    if (-not $unit.Count) { $failures += 'No default skeletal StoneAxe spawned' }
}
if ($Mode -eq 'default_fixture') {
    foreach ($team in @(0,1)) {
        foreach ($slot in @(0,1,2)) {
            if ($log -notmatch "CIVWAR_ROCK_TOWER_FIXTURE team=$team slot=$slot result=0 ") { $failures += "Normal build command failed: team=$team slot=$slot" }
            if (-not ($turret -match "team=$team slot=$slot .*activation=default_runtime")) { $failures += "Default turret absent: team=$team slot=$slot" }
        }
    }
}
$shots = @()
foreach ($file in @(Get-ChildItem -LiteralPath (Join-Path $root 'Saved/Screenshots') -Recurse -File -Filter "${Run}_*.png")) {
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    $width = $bytes[16] * 16777216 + $bytes[17] * 65536 + $bytes[18] * 256 + $bytes[19]
    $height = $bytes[20] * 16777216 + $bytes[21] * 65536 + $bytes[22] * 256 + $bytes[23]
    if ($width -ne 1600 -or $height -ne 900) { $failures += "Unexpected screenshot resolution: $($file.Name)" }
    $shots += @{path=$file.FullName; sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); width=$width; height=$height}
}
if (-not $shots.Count) { $failures += 'No actual image was saved' }
if ($Mode -eq 'base_camera' -and $shots.Count -ne 6) { $failures += 'Both-team three-distance capture is incomplete' }
if ($Mode -eq 'default_fixture') {
    foreach ($team in @(0,1)) {
        foreach ($distance in @(1300,2300,3400)) {
            if (-not (Test-Path -LiteralPath (Join-Path $root "Saved/Screenshots/WindowsEditor/${Run}_team${team}_distance${distance}.png"))) { $failures += 'Missing default base/tower camera image' }
        }
    }
    foreach ($phase in 0..5) {
        if (-not (Test-Path -LiteralPath (Join-Path $root "Saved/Screenshots/WindowsEditor/${Run}_cycle_team0_phase${phase}.png"))) { $failures += 'Missing actual default tower cycle image' }
    }
}
$report = @{
    run=$Run; mode=$Mode; process_id=$process.Id; exit_code=$process.ExitCode; timed_out=$timedOut; arguments=$line
    started_at_utc=$started.ToString('o'); finished_at_utc=[DateTime]::UtcNow.ToString('o'); failures=$failures
    environment_evidence=$environment; base_evidence=$base; unit_spawn_count=$unit.Count; unit_example=@($unit|Select-Object -First 2)
    turret_build_evidence=$turret; turret_release_count=[regex]::Matches($log,'CIVWAR_ROCK_TOWER_RELEASE ').Count
    debug_construction_fixture_count=$fixtureCount; screenshots=$shots; protected_files=$hashes
    perf_evidence=@([regex]::Matches($log,'CIVWAR_PERF[^\r\n]*')|ForEach-Object {$_.Value})
    default_or_legacy_loading_check_passed=($failures.Count -eq 0); visual_reviewed=$false; network_approved=$false; production_approved=$false
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $output 'capture_report.json') -Encoding UTF8
if ($failures.Count) { throw ($failures -join '; ') }
Write-Output "Capture completed: $output; images=$($shots.Count); turret_releases=$($report.turret_release_count)"
