param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z][A-Za-z0-9_]*$')][string]$Run,
    [ValidateSet('menu','settings','credits','guide','single','multi','connecting','battle','lobby')][string]$Scene='battle',
    [ValidateSet(1280,1600,1920)][int]$Width=1600,
    [int]$Height=900,
    [ValidateRange(0,4)][int]$Age=0,
    [ValidateRange(0,4)][int]$PreviewAge=0,
    [ValidateSet('none','settings','leave')][string]$InMatchPanel='none',
    [ValidateRange(0,300)][int]$Duration=0,
    [ValidatePattern('^[\p{L}\p{Nd}_]{1,16}$')][string]$ReviewPlayerName='',
    [switch]$AudioEvidence,
    [switch]$MusicLoopProbe
)
$ErrorActionPreference='Stop'
$taskRoot='F:/code/CivWar'
if (@(Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue | Where-Object { -not $_.HasExited }).Count) { throw 'An Unreal instance is already running. Finish it before capture.' }
$out=Join-Path $taskRoot ".impeccable/review/$Run"
if (Test-Path -LiteralPath $out) { throw 'Choose a new Run name to preserve previous captures.' }
New-Item -ItemType Directory -Path $out | Out-Null
$binary=Get-Item -LiteralPath "$taskRoot/Binaries/Win64/UnrealEditor-CivWar.dll"
if (@(Get-ChildItem -LiteralPath "$taskRoot/Source" -Recurse -File | Where-Object { $_.Extension -in '.h','.cpp' -and $_.LastWriteTimeUtc -gt $binary.LastWriteTimeUtc }).Count) { throw 'Build current source first.' }
$captureDuration=if($Duration -gt 0){$Duration}elseif($Scene -eq 'battle'){95}else{14}
$argsList=@('"F:/code/CivWar/CivWar.uproject"','-game','-RenderOffscreen','-unattended','-nosplash','-nop4','-nosound','-windowed','-ForceRes',"-ResX=$Width","-ResY=$Height",'-noshaderworker','-DDC=InstalledNoZenLocalFallback','-FORCELOGFLUSH','-cwshots',"-cwshotprefix=$Run","-cwreviewduration=$captureDuration",'-ExecCmds="t.MaxFPS 30"',('-abslog="'+$out+'/game.log"'))
$argsList += "-cwpreviewage=$PreviewAge"
if($ReviewPlayerName){$argsList += "-cwname=$ReviewPlayerName"}
if($InMatchPanel -ne 'none'){$argsList += "-cwuiinmatch=$InMatchPanel"}
if($AudioEvidence){$argsList=@($argsList | Where-Object { $_ -ne '-nosound' }); $argsList+='-DeterministicAudio'}
if($MusicLoopProbe){if(-not $AudioEvidence){throw 'MusicLoopProbe requires AudioEvidence.'}; $argsList+='-cwmusicseekend'}
if($Scene -eq 'battle'){
    $argsList += '-cwsingle=0','-cwautoready','-cwperf'
    if($Age -gt 0){$argsList += "-cwerafixture=$Age"}
} elseif($Scene -eq 'lobby') {$argsList += '-cwhost'} elseif($Scene -ne 'menu') {$argsList += "-cwuipage=$Scene"}
$process=Start-Process -FilePath 'G:/epic/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe' -ArgumentList ($argsList -join ' ') -WindowStyle Hidden -PassThru
$process.PriorityClass='BelowNormal'
Write-Output "Capture started: PID=$($process.Id) scene=$Scene ${Width}x${Height}"
$deadline=(Get-Date).AddSeconds($captureDuration + 150)
while(-not $process.HasExited -and (Get-Date) -lt $deadline){Start-Sleep -Seconds 2}
if(-not $process.HasExited){Stop-Process -Id $process.Id; throw 'Capture exceeded its duration plus 150-second startup allowance.'}
$log=Get-Content -LiteralPath "$out/game.log" -Raw
$shots=@(Get-ChildItem -LiteralPath "$taskRoot/Saved/Screenshots/WindowsEditor" -Filter "${Run}_*.png")
foreach($shot in $shots){Copy-Item -LiteralPath $shot.FullName -Destination $out}
$failures=@()
if($process.ExitCode -ne 0){$failures+='Unreal exited with an error.'}
if($log -match 'Fatal error:|Assertion failed:|Ensure condition failed:'){ $failures+='Runtime assertion: inspect game.log.' }
if($log -match 'CIVWAR_(FRONTEND|MENU)_FLOW failed'){ $failures+='Front-end interaction check failed: inspect game.log.' }
if($InMatchPanel -ne 'none' -and $log -notmatch 'CIVWAR_FRONTEND_FLOW passed'){$failures+='Front-end interaction check did not run.'}
if($Scene -eq 'connecting' -and $log -notmatch 'CIVWAR_MENU_FLOW passed'){$failures+='Connection/cancel check did not pass.'}
if($MusicLoopProbe -and $log -notmatch 'CW_MUSIC_LOOP'){$failures+='Music loop overlap was not observed.'}
if($shots.Count -eq 0){$failures+='No screenshots captured.'}
@{scene=$Scene;width=$Width;height=$Height;age=$Age;preview_age=$PreviewAge;in_match_panel=$InMatchPanel;duration=$captureDuration;exit_code=$process.ExitCode;failures=$failures;screenshots=@($shots.Name);audio_mode=$(if($AudioEvidence){'NonRealtimeAudioRenderer; silent output, actual audio components'}else{'nosound'});scope='Local editor standalone capture; not packaged or remote multiplayer verification'} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$out/report.json" -Encoding utf8
Write-Output "Capture finished: screenshots=$($shots.Count), failures=$($failures.Count), output=$out"
$process.Dispose()
if($failures.Count){throw ($failures -join ' ')}
