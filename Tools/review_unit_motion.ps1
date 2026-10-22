param(
    [Parameter(Mandatory=$true)][string]$Run,
    [ValidateRange(60,180)][int]$DurationSeconds=100,
    [int]$CaptureDef=-1
)
$ErrorActionPreference='Stop'
$root='F:/code/CivWar'
if ($Run -notmatch '^[A-Za-z][A-Za-z0-9_]*$') { throw 'Unsafe run name' }
if (@(Get-Process UnrealEditor,UnrealEditor-Cmd,blender -ErrorAction SilentlyContinue).Count) { throw 'Heavy slot occupied' }
$binary=Get-Item -LiteralPath "$root/Binaries/Win64/UnrealEditor-CivWar.dll"
if (@(Get-ChildItem -LiteralPath "$root/Source" -Recurse -File | Where-Object { $_.Extension -in '.cpp','.h' -and $_.LastWriteTimeUtc -gt $binary.LastWriteTimeUtc }).Count) {
    throw 'Build current source before running'
}
$out=Join-Path $root "RawAssets/Art/Tripo_v01/reviews/$Run"
if (Test-Path -LiteralPath $out) { throw 'Choose a new run directory' }
New-Item -ItemType Directory -Path $out | Out-Null
$arguments=@(
    '"F:/code/CivWar/CivWar.uproject"','-game','-RenderOffscreen','-unattended',
    '-nosplash','-nop4','-nosound','-windowed','-ForceRes','-ResX=1600','-ResY=900',
    '-noshaderworker','-DDC=InstalledNoZenLocalFallback','-FORCELOGFLUSH',
    '-cwsingle=0','-cwautoready','-cwstoneerafixture','-cwperf','-cwartmotion','-cwarttiming',
    "-cwarttimingrun=$Run","-cwquitafter=$DurationSeconds",'-cwshots',"-cwshotprefix=$Run",
    '-ExecCmds="t.MaxFPS 60"',('-abslog="'+$out+'/game.log"')
)
if ($CaptureDef -ge 0) {
    $arguments = @($arguments | Where-Object { $_ -ne '-cwshots' })
    $arguments += '-cwmotioncapture',"-cwmotioncapturedef=$CaptureDef"
}
@{arguments=$arguments;fps_cap=60;cpu_affinity=15;fixture='real initial stone training queues';asset_enablement_flags=@();capture_def=$CaptureDef} |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$out/launch.json" -Encoding UTF8
$process=Start-Process -FilePath 'G:/epic/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe' -ArgumentList ($arguments -join ' ') -WindowStyle Hidden -PassThru
$process.Handle | Out-Null
$process.PriorityClass='BelowNormal'
$process.ProcessorAffinity=[IntPtr]15
Write-Output "Motion game PID=$($process.Id)"
$timedOut=-not $process.WaitForExit(($DurationSeconds+120)*1000)
if ($timedOut) { Stop-Process -Id $process.Id; $process.WaitForExit() }
$log=Get-Content -LiteralPath "$out/game.log" -Raw -Encoding UTF8
$motion=@([regex]::Matches($log,'CIVWAR_UNIT_MOTION[^\r\n]*') | ForEach-Object {$_.Value})
$pose=@([regex]::Matches($log,'CIVWAR_UNIT_POSE[^\r\n]*') | ForEach-Object {$_.Value})
$failures=@()
if ($timedOut -or $process.ExitCode -ne 0) { $failures+='Game did not exit successfully' }
if ($log -match 'Fatal error:|Assertion failed:|Ensure condition failed:') { $failures+='Engine failure' }
if ($log -match 'missing usage flag|Default Material will be used') { $failures+='A runtime material fell back to the default material' }
if (-not $motion.Count) { $failures+='No actual continuous movement samples' }
$stopped=@($motion | Where-Object {$_ -notmatch 'stopped_frames=0(?: |$)'})
if ($stopped.Count) { $failures+='Continuous walking contained stopped render frames; inspect motion records' }
$shots=@(Get-ChildItem -LiteralPath "$root/Saved/Screenshots" -Recurse -File -Filter "${Run}_*.png" | ForEach-Object {$_.FullName})
$report=@{
    exit_code=$process.ExitCode;timed_out=$timedOut;pid=$process.Id;failures=$failures;
    motion=$motion;pose_transitions=$pose;shots=$shots;
    tripo_terrain=@([regex]::Matches($log,'CIVWAR_TRIPO_TERRAIN[^\r\n]*') | ForEach-Object {$_.Value});
    death_transitions=@($pose | Where-Object {$_ -match 'to=Death '});
    attack_transitions=@($pose | Where-Object {$_ -match 'to=Attack '});
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$out/motion_report.json" -Encoding UTF8
Write-Output "EXIT=$($process.ExitCode) motion=$($motion.Count) stopped_units=$($stopped.Count) death=$($report.death_transitions.Count)"
Write-Output ($failures -join '; ')
if ($failures.Count) { exit 1 }
