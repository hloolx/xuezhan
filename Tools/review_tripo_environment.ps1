param(
    [string]$EngineRoot = 'G:\epic\UE_5.8',
    [string]$Batch = 'TripoEnvironment',
    [int]$FrameLimit = 30,
    [string]$PartialReviewMap = '',
    [switch]$EndsOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = 'F:\code\CivWar'
if ($Batch -notmatch '^[A-Za-z][A-Za-z0-9_]*$') { throw 'Unsafe screenshot batch name' }
if ($FrameLimit -lt 15 -or $FrameLimit -gt 30) { throw 'Overnight review is capped at 15-30 fps' }
$permanentMapping = Join-Path $projectRoot 'Content\Data\EnvironmentArt.json'
$permanentHash = (Get-FileHash -LiteralPath $permanentMapping -Algorithm SHA256).Hash
$mappingPath = $permanentMapping
$expectedCount = 7
if ($PartialReviewMap) {
    if ($PartialReviewMap -notmatch '^RawAssets/Art/Tripo_v01/reviews/[A-Za-z0-9_/-]+\.json$' -or $PartialReviewMap.Contains('..')) { throw 'Unsafe partial review mapping path' }
    $mappingPath = Join-Path $projectRoot $PartialReviewMap
    $expectedCount = 6
}
$mapping = Get-Content -Raw -LiteralPath $mappingPath | ConvertFrom-Json
if (@($mapping.assets.PSObject.Properties).Count -ne $expectedCount) { throw 'Imported environment asset count mismatch' }
if ($PartialReviewMap -and (-not $mapping.partial_review_only -or $mapping.assets.Env_GrassClump -or $mapping.permanent_runtime_mapping_sha256 -ne $permanentHash)) { throw 'Invalid partial review evidence' }
foreach ($entry in $mapping.assets.PSObject.Properties) {
    if ($entry.Value.source -notmatch '[\\/]tripo_processed[\\/]') { throw "Prototype source still registered: $($entry.Name)" }
}
$reviewDirectory = Join-Path $projectRoot "RawAssets\Art\Tripo_v01\reviews\$Batch"
New-Item -ItemType Directory -Path $reviewDirectory -Force | Out-Null
$results = @()
$resolutions = @(@(1600, 900), @(1920, 1080))
$expectedShots = 6
$quitAfter = 100
if ($EndsOnly) { $resolutions = ,@(1600, 900); $expectedShots = 4; $quitAfter = 80 }
foreach ($resolution in $resolutions) {
    $busy = @(Get-Process blender,UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue)
    if ($busy.Count -gt 0) { throw 'A Blender or UE process already owns the local heavy-work slot' }
    $prefix = "${Batch}_$($resolution[0])x$($resolution[1])"
    $logPath = Join-Path $reviewDirectory "$prefix.log"
    $command = @(
        ('"' + (Join-Path $projectRoot 'CivWar.uproject') + '"'),
        '-game', '-RenderOffscreen', '-unattended', '-nosplash', '-nop4', '-windowed', '-ForceRes', '-noshaderworker', '-DDC=InstalledNoZenLocalFallback',
        "-ResX=$($resolution[0])", "-ResY=$($resolution[1])", '-cwsingle=0', '-cwautoready', '-cwautoplay',
        '-cwartreview', '-cwperf', "-cwquitafter=$quitAfter", "-cwshotprefix=$prefix",
        $(if ($EndsOnly) { '-cwartreviewends' }),
        $(if ($PartialReviewMap) { "-cwartenvironment=$PartialReviewMap" }),
        ('-ExecCmds="t.MaxFPS ' + $FrameLimit + '"'), ('-abslog="' + $logPath + '"')
    ) -join ' '
    $startedAt = [DateTime]::UtcNow
    $process = Start-Process -FilePath (Join-Path $EngineRoot 'Engine\Binaries\Win64\UnrealEditor.exe') -ArgumentList $command -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    try { $process.PriorityClass = 'BelowNormal' } catch { Write-Warning 'Could not lower UE process priority' }
    try { $process.ProcessorAffinity = [IntPtr]15 } catch { Write-Warning 'Could not restrict UE to four logical CPUs' }
    Write-Output "Started review $prefix PID=$($process.Id)"
    if (-not $process.WaitForExit(300000)) {
        Stop-Process -Id $process.Id
        throw 'Owned review process exceeded five-minute limit'
    }
    $logText = Get-Content -Raw -LiteralPath $logPath
    $shotLines = @([regex]::Matches($logText, 'CIVWAR_ART_REVIEW[^\r\n]*') | ForEach-Object { $_.Value })
    $files = @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'Saved\Screenshots') -Recurse -Filter "${prefix}_team*_distance*.png" | Where-Object { $_.LastWriteTimeUtc -ge $startedAt -and $_.Length -gt 24 } | Select-Object -ExpandProperty FullName)
    $imageDimensions = @($files | ForEach-Object {
        $header = [System.IO.File]::ReadAllBytes($_)
        $widthBytes = [byte[]]$header[16..19]; [Array]::Reverse($widthBytes)
        $heightBytes = [byte[]]$header[20..23]; [Array]::Reverse($heightBytes)
        [pscustomobject]@{ path = $_; width = [BitConverter]::ToUInt32($widthBytes, 0); height = [BitConverter]::ToUInt32($heightBytes, 0) }
    })
    $resolutionVerified = $imageDimensions.Count -eq $expectedShots -and @($imageDimensions | Where-Object { $_.width -ne $resolution[0] -or $_.height -ne $resolution[1] }).Count -eq 0
    $loaded = $logText.Contains("[EnvironmentArt] Loaded $expectedCount/7 mother meshes")
    if ($PartialReviewMap) { $loaded = $loaded -and $logText.Contains('CIVWAR_PARTIAL_ENV_REVIEW loaded=6 omitted=Env_GrassClump permanent_mapping_unchanged=true') }
    $results += [pscustomobject]@{
        resolution = $resolution
        exit_code = $process.ExitCode
        log = $logPath
        screenshot_files = $files
        actual_image_dimensions = $imageDimensions
        requested_resolution_verified = $resolutionVerified
        endpoint_review = [bool]$EndsOnly
        camera_evidence = $shotLines
        perf_evidence = @([regex]::Matches($logText, 'CIVWAR_PERF[^\r\n]*') | ForEach-Object { $_.Value })
        instance_evidence = @([regex]::Matches($logText, 'CIVWAR_ART_INSTANCES[^\r\n]*') | ForEach-Object { $_.Value })
        environment_loaded = $loaded
        reviewed_asset_count = $expectedCount
        partial_review_only = [bool]$PartialReviewMap
        grass_deferred_and_hidden = [bool]$PartialReviewMap
        permanent_mapping_unchanged = ((Get-FileHash -LiteralPath $permanentMapping -Algorithm SHA256).Hash -eq $permanentHash)
        started_at_utc = $startedAt.ToString('o')
        requested_fps_cap = $FrameLimit
        visual_review = 'pending_image_inspection'
        scope = 'One standalone match viewed from both camera sides; not multiplayer replication validation'
    }
    $results | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $reviewDirectory 'capture_report.json') -Encoding utf8
    if ($process.ExitCode -ne 0 -or $files.Count -ne $expectedShots -or $shotLines.Count -ne $expectedShots -or -not $loaded -or -not $resolutionVerified) { throw "Capture incomplete or actual resolution mismatch for $prefix" }
    if ((Get-FileHash -LiteralPath $permanentMapping -Algorithm SHA256).Hash -ne $permanentHash) { throw 'Permanent environment mapping changed during temporary review' }
}
Write-Output "Capture report: $(Join-Path $reviewDirectory 'capture_report.json')"
