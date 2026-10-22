param([Parameter(Mandatory=$true)][ValidatePattern('^candidate_[0-9]+$')][string]$Candidate)
$ErrorActionPreference='Stop'
if (@(Get-Process UnrealEditor,UnrealEditor-Cmd,blender -ErrorAction SilentlyContinue).Count) { throw 'Heavy slot occupied' }
$taskRoot='F:/code/CivWar'
$review="$taskRoot/RawAssets/Art/Tripo_v01/reviews/knight_prepare_20261020"
$output="$taskRoot/RawAssets/Art/Tripo_v01/tripo_processed/warhorse_v01/$Candidate"
if (Test-Path -LiteralPath $output) { throw 'Preserve prior output; use a new candidate' }
$arguments=@('--background','--threads','2','--python-exit-code','19','--python',
    ('"'+$taskRoot+'/Tools/Blender/prepare_warhorse_motion.py"'),'--',
    '--source-blend',('"'+$review+'/horse_fbx_bind_01/source_bind.blend"'),
    '--source-pbr',('"'+$taskRoot+'/RawAssets/Art/Tripo_v01/tripo_raw/Mount_Warhorse/web_v01_canonical/pbr.glb"'),
    '--output',('"'+$output+'"'))
$process=Start-Process -FilePath 'C:/Users/12153/devtools/blender-5.2.2/Blender Foundation/Blender 5.2/blender.exe' `
    -ArgumentList ($arguments -join ' ') -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$review/horse_motion_$Candidate.log" -RedirectStandardError "$review/horse_motion_$Candidate.err"
$process.Handle | Out-Null
$process.PriorityClass='BelowNormal'
Write-Output "Horse motion PID=$($process.Id)"
$process.WaitForExit()
Write-Output "EXIT=$($process.ExitCode)"
exit $process.ExitCode
