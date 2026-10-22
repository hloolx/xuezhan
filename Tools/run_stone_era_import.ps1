param(
    [Parameter(Mandatory=$true)][string]$Plan,
    [ValidateSet('initial','fresh')][string]$Stage = 'initial'
)
$ErrorActionPreference = 'Stop'
$root = 'F:/code/CivWar'
$planPath = (Resolve-Path -LiteralPath $Plan).Path
if (@(Get-Process UnrealEditor,UnrealEditor-Cmd,blender -ErrorAction SilentlyContinue).Count) {
    throw 'Heavy slot occupied'
}
$out = Split-Path -Parent $planPath
$log = Join-Path $out ($Stage + '_ue.log')
if (Test-Path -LiteralPath $log) { throw 'Preserve earlier log; choose a new plan directory' }
$env:CIVWAR_STONE_ERA_IMPORT_PLAN = $planPath
$env:CIVWAR_STONE_ERA_IMPORT_STAGE = $Stage
# These passes import and inspect persisted asset data. Render the game in a
# separate process; enabling commandlet rendering also compiles editor debug shaders.
$arguments = @(
    '"F:/code/CivWar/CivWar.uproject"', '-run=pythonscript',
    '-script="F:/code/CivWar/Tools/Unreal/import_stone_era_batch.py"',
    '-unattended', '-nosplash', '-nop4', '-nosound', '-NullRHI',
    '-noshaderworker', '-DDC=InstalledNoZenLocalFallback', '-FORCELOGFLUSH',
    ('-abslog="' + $log + '"')
) -join ' '
$process = Start-Process -FilePath 'G:/epic/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe' -ArgumentList $arguments -WindowStyle Hidden -PassThru
$handle = $process.Handle
$process.PriorityClass = 'BelowNormal'
$process.ProcessorAffinity = [IntPtr]15
Write-Output "Stone era import PID=$($process.Id) stage=$Stage log=$log"
$process.WaitForExit()
Write-Output "Stone era import EXIT=$($process.ExitCode)"
exit $process.ExitCode
