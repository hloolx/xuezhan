param([Parameter(Mandatory=$true)][string]$Plan)
$ErrorActionPreference='Stop'
if (@(Get-Process UnrealEditor,UnrealEditor-Cmd,blender -ErrorAction SilentlyContinue).Count) { throw 'Heavy slot occupied' }
$planPath=(Resolve-Path -LiteralPath $Plan).Path
$out=Split-Path -Parent $planPath
$log=Join-Path $out 'initial_ue.log'
if (Test-Path -LiteralPath $log) { throw 'Use a fresh import plan directory' }
$env:CIVWAR_ERA_IMPORT_PLAN=$planPath
$env:CIVWAR_ERA_IMPORT_STAGE='initial'
$arguments=@(
    '"F:/code/CivWar/CivWar.uproject"','-run=pythonscript',
    '-script="F:/code/CivWar/Tools/Unreal/import_era_assets.py"',
    '-unattended','-nosplash','-nop4','-nosound','-NullRHI',
    '-noshaderworker','-DDC=InstalledNoZenLocalFallback','-FORCELOGFLUSH',
    ('-abslog="'+$log+'"')
)
$process=Start-Process -FilePath 'G:/epic/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe' -ArgumentList ($arguments -join ' ') -WindowStyle Hidden -PassThru
$process.Handle | Out-Null
$process.PriorityClass='BelowNormal'
$process.ProcessorAffinity=[IntPtr]15
Write-Output "Era import PID=$($process.Id)"
$process.WaitForExit()
Write-Output "EXIT=$($process.ExitCode)"
exit $process.ExitCode
