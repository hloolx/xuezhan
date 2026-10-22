param(
    [Parameter(Mandatory=$true)][string]$Run,
    [Parameter(Mandatory=$true)][ValidateRange(1,4)][int]$Age,
    [ValidateRange(100,240)][int]$DurationSeconds=150,
    [switch]$MotionCapture
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
if (Test-Path -LiteralPath $out) { throw 'Choose a new run directory' }
New-Item -ItemType Directory -Path $out | Out-Null
$arguments=@(
    '"F:/code/CivWar/CivWar.uproject"','-game','-RenderOffscreen','-unattended',
    '-nosplash','-nop4','-nosound','-windowed','-ForceRes','-ResX=1600','-ResY=900',
    '-noshaderworker','-DDC=InstalledNoZenLocalFallback','-FORCELOGFLUSH',
    '-cwsingle=0','-cwautoready',"-cwerafixture=$Age",'-cwperf','-cwartmotion','-cwarttiming',
    "-cwarttimingrun=$Run","-cwquitafter=$DurationSeconds",'-cwshots',"-cwshotprefix=$Run",
    '-ExecCmds="t.MaxFPS 60"',('-abslog="'+$out+'/game.log"')
)
if ($MotionCapture) {
    $arguments = @($arguments | Where-Object { $_ -ne '-cwshots' })
    $arguments += '-cwmotioncapture'
}
@{arguments=$arguments;age=$Age;fps_cap=60;cpu_affinity=15;asset_enablement_flags=@();motion_capture=[bool]$MotionCapture} |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$out/launch.json" -Encoding UTF8
$process=Start-Process -FilePath 'G:/epic/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe' -ArgumentList ($arguments -join ' ') -WindowStyle Hidden -PassThru
$process.Handle | Out-Null
$process.PriorityClass='BelowNormal'
$process.ProcessorAffinity=[IntPtr]15
Write-Output "Era game PID=$($process.Id) age=$Age"
$timedOut=-not $process.WaitForExit(($DurationSeconds+120)*1000)
if ($timedOut) { Stop-Process -Id $process.Id; $process.WaitForExit() }
@{exit_code=$process.ExitCode;timed_out=$timedOut;pid=$process.Id} |
    ConvertTo-Json | Set-Content -LiteralPath "$out/process.json" -Encoding UTF8
if ($timedOut -or $process.ExitCode -ne 0) { throw "Game did not exit successfully: $($process.ExitCode)" }
& python -X utf8 "$taskRoot/Tools/validate_era_gameplay.py" $out --age $Age
exit $LASTEXITCODE
