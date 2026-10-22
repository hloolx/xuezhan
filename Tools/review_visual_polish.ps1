param(
    [Parameter(Mandatory=$true)][string]$Run,
    [ValidateRange(1,4)][int]$Age=4,
    [ValidateSet('environment','base','units')][string]$Focus='environment'
)
$ErrorActionPreference='Stop'
$taskRoot='F:/code/CivWar'
if ($Run -notmatch '^[A-Za-z][A-Za-z0-9_]*$') { throw 'Unsafe run name' }
if (@(Get-Process UnrealEditor,UnrealEditor-Cmd,blender -ErrorAction SilentlyContinue).Count) { throw 'Heavy slot occupied' }
$binary=Get-Item -LiteralPath "$taskRoot/Binaries/Win64/UnrealEditor-CivWar.dll"
if (@(Get-ChildItem -LiteralPath "$taskRoot/Source" -Recurse -File | Where-Object { $_.Extension -in '.cpp','.h' -and $_.LastWriteTimeUtc -gt $binary.LastWriteTimeUtc }).Count) {
    throw 'Build current source before running'
}
$out=Join-Path $taskRoot "RawAssets/Art/Tripo_v01/reviews/$Run"
if (Test-Path -LiteralPath $out) { throw 'Preserve existing evidence; choose a new run name' }
New-Item -ItemType Directory -Path $out | Out-Null
$arguments=@(
    '"F:/code/CivWar/CivWar.uproject"','-game','-RenderOffscreen','-unattended',
    '-nosplash','-nop4','-nosound','-windowed','-ForceRes','-ResX=1600','-ResY=900',
    '-noshaderworker','-DDC=InstalledNoZenLocalFallback','-FORCELOGFLUSH',
    '-cwsingle=0','-cwautoready',"-cwerafixture=$Age",'-cwperf','-cwartreview',
    '-cwartreviewstart=40','-cwquitafter=120',"-cwshotprefix=$Run",
    '-ExecCmds="t.MaxFPS 30"',('-abslog="'+$out+'/game.log"')
)
if ($Focus -eq 'base') { $arguments += '-cwbaseartreview','-cwbasearthideui' }
if ($Focus -eq 'units') { $arguments += '-cwunitartreview' }
@{arguments=$arguments;age=$Age;focus=$Focus;fps_cap=30;cpu_affinity=15;asset_enablement_flags=@();review_start_match_seconds=40} |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$out/launch.json" -Encoding UTF8
$process=Start-Process -FilePath 'G:/epic/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe' -ArgumentList ($arguments -join ' ') -WindowStyle Hidden -PassThru
$process.Handle | Out-Null
$process.PriorityClass='BelowNormal'
$process.ProcessorAffinity=[IntPtr]15
Write-Output "Polish review PID=$($process.Id) age=$Age focus=$Focus"
$timedOut=-not $process.WaitForExit(240000)
if ($timedOut) { Stop-Process -Id $process.Id; $process.WaitForExit() }
$log=Get-Content -LiteralPath "$out/game.log" -Raw -Encoding UTF8
$failures=@()
if ($timedOut -or $process.ExitCode -ne 0) { $failures+='Review process failed' }
if ($log -match 'Fatal error:|Assertion failed:|Ensure condition failed:|Failed to compile Material|LogMaterial: Error|missing usage flag|Default Material will be used') { $failures+='Engine or material failure; inspect game.log' }
foreach ($team in @(0,1)) {
    if ($log -notmatch "CIVWAR_ERA_FIXTURE_READY team=$team age=$Age ") { $failures+="Era fixture missing for team $team" }
}
$shots=@()
foreach ($team in @(0,1)) {
    foreach ($distance in @(1300,2300,3400)) {
        $name="${Run}_team${team}_distance${distance}.png"
        $path="$taskRoot/Saved/Screenshots/WindowsEditor/$name"
        if (-not (Test-Path -LiteralPath $path)) { $failures+="Missing $name"; continue }
        $shots+=@{path=$path;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant();team=$team;distance=$distance}
    }
}
$camera=@([regex]::Matches($log,'CIVWAR_ART_REVIEW [^\r\n]*') | ForEach-Object {$_.Value})
if ($camera.Count -ne 6) { $failures+='Expected six recorded camera poses' }
$report=@{
    pid=$process.Id;exit_code=$process.ExitCode;timed_out=$timedOut;age=$Age;focus=$Focus;
    failures=$failures;screenshots=$shots;camera_evidence=$camera;
    terrain=@([regex]::Matches($log,'CIVWAR_NATURAL_TERRAIN [^\r\n]*') | ForEach-Object {$_.Value});
    layout=@([regex]::Matches($log,'CIVWAR_ENVIRONMENT_LAYOUT [^\r\n]*') | ForEach-Object {$_.Value});
    instances=@([regex]::Matches($log,'CIVWAR_ART_INSTANCES [^\r\n]*') | ForEach-Object {$_.Value});
    actual_visual_inspection='pending';scope='Explicit diagnostic camera, same normal default assets; not multiplayer or packaged release'
}
$report | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath "$out/capture_report.json" -Encoding UTF8
Write-Output "EXIT=$($process.ExitCode) shots=$($shots.Count) failures=$($failures.Count)"
if ($failures.Count) { throw ($failures -join '; ') }
