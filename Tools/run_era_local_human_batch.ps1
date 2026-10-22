param([Parameter(Mandatory=$true)][string]$Queue)
$ErrorActionPreference = 'Stop'
$root = 'F:/code/CivWar'
$queuePath = (Resolve-Path -LiteralPath $Queue).Path
$data = Get-Content -LiteralPath $queuePath -Raw | ConvertFrom-Json
if ($data.schema -ne 'explicit_local_human_binding_queue_v1') { throw 'Wrong local-authoring queue' }
if ((Get-FileHash -LiteralPath $data.input_plan.path -Algorithm SHA256).Hash.ToLower() -ne $data.input_plan.sha256) {
    throw 'Frozen local-authoring plan changed'
}
$logRoot = Split-Path -Parent $queuePath
$reportPath = Join-Path $logRoot 'dcc_batch_report.json'
if (Test-Path -LiteralPath $reportPath) { throw 'Preserve earlier execution' }
$results = [System.Collections.Generic.List[object]]::new()
foreach ($task in $data.tasks) {
    if (@(Get-Process UnrealEditor,UnrealEditor-Cmd,blender -ErrorAction SilentlyContinue).Count) { throw 'Heavy slot occupied' }
    if ($task.asset -notmatch '^[A-Za-z][A-Za-z0-9_]*$') { throw 'Unsafe asset id' }
    foreach ($target in @($task.output, $task.binding_output)) {
        $resolved = [System.IO.Path]::GetFullPath($target)
        $workspace = [System.IO.Path]::GetFullPath('F:/code/血战文明/RawAssets/Art/Tripo_v01/tripo_processed') + [System.IO.Path]::DirectorySeparatorChar
        if (-not $resolved.StartsWith($workspace, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Target leaves derived workspace' }
        if (Test-Path -LiteralPath $target) { throw 'Preserve existing local candidate' }
    }
    $arguments = @('-b','-t','2','--python-exit-code','19','--python',($root+'/Tools/Blender/author_local_human_bind.py'),
        '--','--plan',$data.input_plan.path,'--asset',$task.asset,'--binding-output',$task.binding_output,
        '--output',$task.output,'--regions',$task.regions,'--render')
    if (@($arguments | Where-Object { $_.Contains('"') }).Count) { throw 'Unexpected quote' }
    $line = ($arguments | ForEach-Object { '"'+$_+'"' }) -join ' '
    $process = Start-Process -FilePath 'C:/Users/12153/devtools/blender-5.2.2/Blender Foundation/Blender 5.2/blender.exe' `
        -ArgumentList $line -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot ($task.asset+'.stdout.log')) `
        -RedirectStandardError (Join-Path $logRoot ($task.asset+'.stderr.log'))
    $handle = $process.Handle
    $process.PriorityClass = 'BelowNormal'
    Write-Output ($task.asset+' PID='+$process.Id)
    $process.WaitForExit()
    $manifest = Join-Path $task.output 'manifest.json'
    $success = $process.ExitCode -eq 0 -and (Test-Path -LiteralPath $manifest)
    $results.Add(@{asset=$task.asset;process_id=$process.Id;exit_code=$process.ExitCode;
        status=$(if($success){'local_binding_pending_actual_visual_and_unreal'}else{'failed'});
        manifest=$manifest;rig_origin='local_authored'})
    @{queue=$queuePath;results=@($results.ToArray());runtime_config_written=$false} |
        ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Output ($task.asset+' EXIT='+$process.ExitCode)
    if (-not $success) { throw ('Local binding failed; preserve candidate '+$task.asset) }
}
