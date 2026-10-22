param(
    [Parameter(Mandatory=$true)][string]$Queue
)
# Run only while holding root's current heavy-task lease. This does not import
# UE assets, approve visuals, or update any default-runtime mapping.
$ErrorActionPreference = 'Stop'
$root = 'F:/code/CivWar'
$queuePath = (Resolve-Path -LiteralPath $Queue).Path
$queueData = Get-Content -LiteralPath $queuePath -Raw | ConvertFrom-Json
if ($queueData.schema -ne 'actual_human_dcc_queue_v1') { throw 'Unsupported source queue' }
if ((Get-FileHash -LiteralPath $queueData.input_plan -Algorithm SHA256).Hash.ToLower() -ne $queueData.input_plan_sha256) {
    throw 'Frozen source plan changed; prepare a new queue'
}
$reportPath = Join-Path (Split-Path -Parent $queuePath) 'dcc_batch_report.json'
if (Test-Path -LiteralPath $reportPath) { throw 'Keep earlier execution report; prepare a new queue' }
$results = [System.Collections.Generic.List[object]]::new()
$executable = 'C:/Users/12153/devtools/blender-5.2.2/Blender Foundation/Blender 5.2/blender.exe'
foreach ($task in $queueData.tasks) {
    if ($task.status -ne 'ready_for_leased_dcc') {
        $results.Add(@{asset=$task.asset;status=$task.status})
        continue
    }
    if (@(Get-Process UnrealEditor,UnrealEditor-Cmd,blender -ErrorAction SilentlyContinue).Count) { throw 'Heavy slot occupied' }
    if ($task.asset -notmatch '^[A-Za-z][A-Za-z0-9_]*$') { throw 'Unsafe asset id' }
    $resolvedOutput = [System.IO.Path]::GetFullPath($task.output)
    $workspace = [System.IO.Path]::GetFullPath('F:/code/血战文明/RawAssets/Art/Tripo_v01/tripo_processed') + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolvedOutput.StartsWith($workspace, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Output leaves owned derived workspace' }
    if (Test-Path -LiteralPath $resolvedOutput) { throw 'Do not replace an existing candidate' }
    $logRoot = Split-Path -Parent $queuePath
    $stdout = Join-Path $logRoot ($task.asset+'.stdout.log')
    $stderr = Join-Path $logRoot ($task.asset+'.stderr.log')
    $arguments = @('-b','-t','2','--python-exit-code','19','--python',($root+'/Tools/Blender/prepare_era_character.py'),
                   '--','--plan',$queueData.input_plan,'--asset',$task.asset,'--output',$resolvedOutput,'--render')
    if (@($arguments | Where-Object { $_.Contains('"') }).Count) { throw 'Unsupported quote in source path' }
    $argumentLine = ($arguments | ForEach-Object { '"'+$_+'"' }) -join ' '
    $process = Start-Process -FilePath $executable -ArgumentList $argumentLine -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $handle = $process.Handle
    $process.PriorityClass = 'BelowNormal'
    Write-Output ($task.asset+' PID='+$process.Id)
    $process.WaitForExit()
    $manifest = Join-Path $resolvedOutput 'manifest.json'
    $success = $process.ExitCode -eq 0 -and (Test-Path -LiteralPath $manifest)
    $results.Add(@{asset=$task.asset;process_id=$process.Id;exit_code=$process.ExitCode;
                  status=$(if($success){'dcc_saved_pending_actual_visual_and_unreal'}else{'failed'});
                  manifest=$manifest;output=$resolvedOutput})
    @{queue=$queuePath;results=@($results.ToArray());runtime_config_written=$false;production_approved=$false} |
        ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Output ($task.asset+' EXIT='+$process.ExitCode)
    if (-not $success) { throw ('DCC failed; preserve logs and inspect '+$task.asset) }
}
@{queue=$queuePath;results=@($results.ToArray());runtime_config_written=$false;production_approved=$false} |
    ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $reportPath -Encoding utf8
