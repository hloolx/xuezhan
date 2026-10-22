param(
    [string]$EngineRoot = 'G:\epic\UE_5.8',
    [string]$Run = 'StoneAxeTiming_' + (Get-Date -Format 'yyyyMMdd_HHmmss'),
    [int]$DurationSeconds = 120,
    [int]$FrameLimit = 20,
    [int]$Width = 960,
    [int]$Height = 540,
    [string]$Python = 'python',
    [switch]$FollowPilot,
    [string]$PartialReviewMap = '',
    [switch]$PresentationDelayTest,
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
$projectRoot = 'F:\code\CivWar'
$project = Join-Path $projectRoot 'CivWar.uproject'
$editor = Join-Path $EngineRoot 'Engine\Binaries\Win64\UnrealEditor.exe'
$configPath = Join-Path $projectRoot 'Content\Data\UnitArtPilot.json'
$output = Join-Path $projectRoot "RawAssets\Art\Tripo_v01\reviews\$Run"
$logPath = Join-Path $output 'standalone.log'
$timingPath = Join-Path $output 'timing_report.json'
$capturePath = Join-Path $output 'capture_report.json'
$validator = Join-Path $projectRoot 'Tools\validate_stoneaxe_timing.py'
if ($Run -notmatch '^[A-Za-z][A-Za-z0-9_]*$') { throw 'Use a fresh alphanumeric run token beginning with a letter' }
if ($DurationSeconds -lt 75 -or $DurationSeconds -gt 300) { throw 'Review duration must be 75-300 seconds' }
if ($FrameLimit -lt 15 -or $FrameLimit -gt 30) { throw 'Review frame cap must be 15-30 fps' }
if ($Width -lt 640 -or $Width -gt 1920 -or $Height -lt 360 -or $Height -gt 1080) { throw 'Review resolution must stay within 640x360 to 1920x1080' }

$blockers = @()
$partialMappingPath = $null
$partialMappingHash = $null
$permanentEnvironmentPath = Join-Path $projectRoot 'Content\Data\EnvironmentArt.json'
$permanentEnvironmentHash = $null
if ($PartialReviewMap) {
    if ($PartialReviewMap -notmatch '^RawAssets/Art/Tripo_v01/reviews/[A-Za-z0-9_/-]+\.json$' -or $PartialReviewMap.Contains('..')) { throw 'Unsafe partial review mapping path' }
    $partialMappingPath = Join-Path $projectRoot $PartialReviewMap
    try {
        $mapping = Get-Content -LiteralPath $partialMappingPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $partialMappingHash = (Get-FileHash -LiteralPath $partialMappingPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $permanentEnvironmentHash = (Get-FileHash -LiteralPath $permanentEnvironmentPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $expectedIds = @('Env_BoulderA', 'Env_BoulderB', 'Env_RockSlab', 'Env_Broadleaf', 'Env_Pine', 'Env_Shrub')
        $actualIds = @($mapping.assets.PSObject.Properties | ForEach-Object { $_.Name })
        if ($mapping.partial_review_only -ne $true -or $mapping.production_approved -ne $false -or $mapping.hide_deferred_grass -ne $true -or $actualIds.Count -ne 6 -or @($actualIds | Where-Object { $_ -notin $expectedIds }).Count -gt 0 -or $mapping.permanent_runtime_mapping_sha256 -ne $permanentEnvironmentHash) {
            throw 'Partial mapping must be the non-production six-asset review with grass hidden and the permanent mapping hash unchanged'
        }
        foreach ($entry in $mapping.assets.PSObject.Properties) {
            if ($entry.Value.source -notmatch '[\\/]tripo_processed[\\/]' -or $entry.Value.object_path -notmatch '^/Game/ArtPilot/') { throw "Non-Tripo or non-isolated environment source: $($entry.Name)" }
            if ((Get-FileHash -LiteralPath $entry.Value.source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value.source_sha256) { throw "Environment source hash changed: $($entry.Name)" }
        }
    } catch {
        $blockers += 'Partial environment preflight failed: ' + $_.Exception.Message
    }
}
foreach ($required in @($project, $editor, $validator)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { $blockers += "Missing file: $required" }
}
if (Test-Path -LiteralPath $output) { $blockers += 'Output directory already exists; choose a fresh Run to preserve evidence' }
$config = $null
$configHash = $null
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    $blockers += 'Approved UnitArtPilot.json is absent; -cwstoneaxepilot alone leaves the prototype active'
} else {
    try {
        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $configHash = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($config.enabled -ne $true -or $config.ue_structural_approved -ne $true -or $config.socket_alignment_approved -ne $true -or $config.asset_id -ne 'Unit_StoneAxe' -or $config.socket_name -ne 'weapon_r') {
            $blockers += 'Pilot configuration does not carry the required explicit enabled/structural/socket approvals'
        }
        $meshPath = [string]$config.skeletal_mesh
        if ($meshPath -notmatch '^(/Game/ArtPilot/StoneAxeRig/h[0-9a-f]{16})/SK_StoneAxe_Pilot(?:\.SK_StoneAxe_Pilot)?$') {
            $blockers += 'Pilot body is not the isolated hash-directory asset'
        } else {
            $destination = $Matches[1]
            $assets = @($meshPath, [string]$config.weapon_mesh)
            if ([string]$config.weapon_mesh -notmatch ('^' + [regex]::Escape($destination + '/Weapon/SM_StoneAxe_Fitted') + '(?:\.SM_StoneAxe_Fitted)?$')) {
                $blockers += 'Pilot weapon does not belong to the same isolated delivery'
            }
            foreach ($clip in @('Idle', 'Move', 'Attack', 'Hit', 'Death')) {
                $clipPath = [string]$config.animations.$clip
                if ($clipPath -notmatch ('^' + [regex]::Escape($destination + '/Animations/AN_StoneAxe_' + $clip) + '(?:\.AN_StoneAxe_' + $clip + ')?$')) {
                    $blockers += "Missing or unrelated animation: $clip"
                }
                $assets += $clipPath
            }
            foreach ($asset in $assets) {
                if (-not $asset.StartsWith($destination + '/')) { continue }
                $package = $asset.Split('.')[0].Substring('/Game/'.Length).Replace('/', '\') + '.uasset'
                if (-not (Test-Path -LiteralPath (Join-Path (Join-Path $projectRoot 'Content') $package) -PathType Leaf)) {
                    $blockers += "Missing on-disk pilot package: $asset"
                }
            }
        }
    } catch {
        $blockers += 'Pilot configuration could not be validated: ' + $_.Exception.Message
    }
}

$arguments = @(
    ('"' + $project + '"'), '-game', '-RenderOffscreen', '-unattended', '-nosplash', '-nop4', '-windowed', '-ForceRes',
    '-noshaderworker', '-DDC=InstalledNoZenLocalFallback', "-ResX=$Width", "-ResY=$Height",
    '-cwsingle=0', '-cwautoplay', '-cwautoready', '-cwstoneaxepilot', '-cwarttiming', "-cwarttimingrun=$Run",
    '-cwartreview', '-cwperf', "-cwshotprefix=$Run", "-cwquitafter=$DurationSeconds",
    $(if ($FollowPilot) { '-cwunitartreview' }), $(if ($PartialReviewMap) { "-cwartenvironment=$PartialReviewMap" }),
    $(if ($PresentationDelayTest) { '-cwartpresentationdelay=450' }),
    ('-ExecCmds="t.MaxFPS ' + $FrameLimit + '"'), ('-abslog="' + $logPath + '"')
) -join ' '
$scope = 'Single standalone authority with local presentation; not remote replication, late-join, or production approval'
if ($PresentationDelayTest) { $scope = 'Controlled 450ms local presentation delay of genuine standalone snapshots; not network transmission, late-join, or production approval' }
$limits = @(
    'Natural combat may provide both-team normal and cancellation samples; coverage is determined only from the actual logs',
    'No guaranteed initial-active or late-delivery snapshots exist in this single-process path',
    'Both camera sides are not two network clients',
    'The runner never creates approvals, modifies pilot configuration, changes gameplay, or relaxes timing coverage'
)
if ($PresentationDelayTest) {
    $limits[1] = 'Initial-active and late snapshot coverage must be observed from real delayed presentation; no network transport delay is introduced'
    $limits += 'Only the first ordinary StoneAxe per team is delayed; other units remain normal controls, and actual timing logs determine coverage'
}
if (-not $Execute) {
    [pscustomobject]@{ dry_run = $true; executable = $editor; arguments = $arguments; output = $output; blockers = $blockers; scope = $scope; limits = $limits; follow_pilot = [bool]$FollowPilot; partial_review_map = $PartialReviewMap; partial_review_map_sha256 = $partialMappingHash; presentation_delay_test = [bool]$PresentationDelayTest } | ConvertTo-Json -Depth 6
    exit 0
}
if ($blockers.Count -gt 0) { throw ($blockers -join '; ') }
if (@(Get-Process blender,UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue).Count -gt 0) { throw 'Another Blender or UE process owns the heavy-work slot' }
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) { throw 'Python executable not found' }
New-Item -ItemType Directory -Path $output -ErrorAction Stop | Out-Null
$process = $null
$started = [DateTime]::UtcNow
$failure = $null
$timedOut = $false
$exitCode = $null
$analysisExitCode = $null
try {
    $process = Start-Process -FilePath $editor -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    try { $process.PriorityClass = 'BelowNormal' } catch { Write-Warning 'Could not lower owned process priority' }
    try { $process.ProcessorAffinity = [IntPtr]15 } catch { Write-Warning 'Could not restrict owned process to four logical CPUs' }
    Write-Output "Started single-process timing review PID=$($process.Id), run=$Run"
    if (-not $process.WaitForExit(($DurationSeconds + 120) * 1000)) {
        $timedOut = $true
        $process.Kill()
        $process.WaitForExit()
    }
    $process.Refresh()
    $exitCode = $process.ExitCode
} catch {
    $failure = $_.Exception.Message
} finally {
    if ($process -and -not $process.HasExited) {
        $process.Kill()
        $process.WaitForExit()
    }
}

$logText = ''
$logRecord = $null
if (Test-Path -LiteralPath $logPath -PathType Leaf) {
    $logText = Get-Content -LiteralPath $logPath -Raw -Encoding UTF8
    $logRecord = [pscustomobject]@{ path = $logPath; bytes = (Get-Item -LiteralPath $logPath).Length; sha256 = (Get-FileHash -LiteralPath $logPath -Algorithm SHA256).Hash.ToLowerInvariant() }
    try {
        $previousPythonUtf8 = $env:PYTHONUTF8
        $env:PYTHONUTF8 = '1'
        & $Python $validator --logs $logPath --run $Run --report $timingPath
        $analysisExitCode = $LASTEXITCODE
    } catch {
        $failure = 'Timing analyzer execution failed: ' + $_.Exception.Message
    } finally {
        $env:PYTHONUTF8 = $previousPythonUtf8
    }
} else {
    $failure = 'Owned process produced no readable runtime log'
}
$screenshots = @()
$screenshotRoot = Join-Path $projectRoot 'Saved\Screenshots'
if (Test-Path -LiteralPath $screenshotRoot) {
    $screenshots = @(Get-ChildItem -LiteralPath $screenshotRoot -Recurse -Filter "${Run}_team*_distance*.png" | Where-Object { $_.LastWriteTimeUtc -ge $started -and $_.Length -gt 24 } | ForEach-Object {
        [pscustomobject]@{ path = $_.FullName; bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
}
$configUnchanged = (Test-Path -LiteralPath $configPath) -and (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash.ToLowerInvariant() -eq $configHash
$pilotCreated = $logText.Contains('CIVWAR_STONEAXE_PILOT mesh=')
$clientSamples = [regex]::Matches($logText, 'CIVWAR_ART_TIMING[^\r\n]*role=client[^\r\n]*event=sample').Count
$delayLines = @([regex]::Matches($logText, 'CIVWAR_PRESENTATION_DELAY[^\r\n]*') | ForEach-Object { $_.Value })
$delayFailure = @($delayLines | Where-Object { $_ -match 'status=(failed|rejected)\b' }).Count -gt 0
$delayEnabled = @($delayLines | Where-Object { $_ -match 'status=enabled\b' }).Count -gt 0
if ($PresentationDelayTest -and (-not $delayEnabled -or $delayFailure)) { $failure = 'Presentation delay test did not activate or reported a real diagnostic failure' }
$environmentUnchanged = $true
$partialEnvironmentLoaded = $null
if ($PartialReviewMap) {
    $environmentUnchanged = (Get-FileHash -LiteralPath $permanentEnvironmentPath -Algorithm SHA256).Hash.ToLowerInvariant() -eq $permanentEnvironmentHash -and (Get-FileHash -LiteralPath $partialMappingPath -Algorithm SHA256).Hash.ToLowerInvariant() -eq $partialMappingHash
    $partialEnvironmentLoaded = $logText.Contains('[EnvironmentArt] Loaded 6/7 mother meshes') -and $logText.Contains('CIVWAR_PARTIAL_ENV_REVIEW loaded=6 omitted=Env_GrassClump permanent_mapping_unchanged=true')
}
[pscustomobject]@{
    mode = 'single_standalone'; run = $Run; scope = $scope; limits = $limits; executable = $editor; arguments = $arguments
    pid = $(if ($process) { $process.Id } else { $null }); started_at_utc = $started.ToString('o'); finished_at_utc = [DateTime]::UtcNow.ToString('o')
    exit_code = $exitCode; timed_out = $timedOut; failure = $failure; config_path = $configPath; config_sha256 = $configHash; config_unchanged = $configUnchanged
    actual_pilot_created = $pilotCreated; actual_client_samples = $clientSamples; log = $logRecord
    follow_pilot = [bool]$FollowPilot; partial_review_map = $PartialReviewMap; partial_review_map_sha256 = $partialMappingHash
    presentation_delay_test = [bool]$PresentationDelayTest; presentation_delay_ms = $(if ($PresentationDelayTest) { 450 } else { 0 }); presentation_delay_evidence = $delayLines
    permanent_environment_sha256 = $permanentEnvironmentHash; environment_mappings_unchanged = $environmentUnchanged; partial_environment_loaded = $partialEnvironmentLoaded
    analyzer_exit_code = $analysisExitCode; timing_report = $timingPath; screenshots = $screenshots; expected_camera_shots = 6
    camera_evidence = @([regex]::Matches($logText, 'CIVWAR_ART_REVIEW[^\r\n]*') | ForEach-Object { $_.Value })
    perf_evidence = @([regex]::Matches($logText, 'CIVWAR_PERF[^\r\n]*') | ForEach-Object { $_.Value })
    visual_approved = $false; network_timing_approved = $false; production_approved = $false
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $capturePath -Encoding utf8
Write-Output "Capture evidence: $capturePath"
if ($failure -or $timedOut -or $exitCode -ne 0 -or -not $configUnchanged -or -not $environmentUnchanged -or ($PartialReviewMap -and -not $partialEnvironmentLoaded) -or -not $pilotCreated -or $clientSamples -eq 0) { exit 1 }
if ($analysisExitCode -eq 1) { exit 1 }
if ($analysisExitCode -ne 0) { exit 2 }
exit 0
