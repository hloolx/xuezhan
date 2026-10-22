param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z][A-Za-z0-9_]*$')][string]$Run,
    [ValidateRange(30,240)][int]$TimeoutSeconds=150
)

# A bounded loopback login check, not a match or multiplayer endurance test.
# -nowrite disables config writes in UE's ConfigCacheIni on both processes.
$ErrorActionPreference='Stop'
$taskRoot='F:/code/CivWar'
$enginePath='G:/epic/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe'
$loginPort=17779
$hostName='血战房主甲'
$clientName='文明来客乙'
$out=Join-Path $taskRoot "reviews/$Run"
if(Test-Path -LiteralPath $out){throw 'Choose a new Run name; existing evidence is preserved.'}
if(@(Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue | Where-Object {-not $_.HasExited}).Count){
    throw 'Finish existing Unreal captures before running this isolated login check.'
}
if(@(Get-NetUDPEndpoint -LocalPort $loginPort -ErrorAction SilentlyContinue).Count){
    throw "Loopback login test port $loginPort is already in use."
}
$binary=Get-Item -LiteralPath "$taskRoot/Binaries/Win64/UnrealEditor-CivWar.dll"
if(@(Get-ChildItem -LiteralPath "$taskRoot/Source" -Recurse -File | Where-Object {$_.Extension -in '.h','.cpp' -and $_.LastWriteTimeUtc -gt $binary.LastWriteTimeUtc}).Count){
    throw 'Build current source before checking the login path.'
}
New-Item -ItemType Directory -Path $out | Out-Null
$hostLog=Join-Path $out 'host.log'
$clientLog=Join-Path $out 'client.log'
$ownedProcesses=@()
$failures=[Collections.Generic.List[string]]::new()
$hostReady=$false
$hostNameInTravel=$false
$clientReceived=$false
$requestEvidence=''
$successEvidence=''
$started=[DateTime]::UtcNow

function Read-LoginLog([string]$Path){
    if(Test-Path -LiteralPath $Path){return Get-Content -LiteralPath $Path -Raw -Encoding utf8}
    return ''
}
function Get-UserSettingsDigest {
    $digest=@{}
    $configPath=Join-Path $taskRoot 'Saved/Config'
    if(Test-Path -LiteralPath $configPath){
        foreach($file in Get-ChildItem -LiteralPath $configPath -Filter GameUserSettings.ini -Recurse -File){
            $digest[$file.FullName]=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        }
    }
    return $digest
}
$settingsBefore=Get-UserSettingsDigest
$commonArgs=@('"F:/code/CivWar/CivWar.uproject"','-game','-nullrhi','-nosound','-unattended','-nosplash','-nop4',
    '-nowrite','-multiprocess','-DDC=InstalledNoZenLocalFallback','-FORCELOGFLUSH','-ExecCmds="t.MaxFPS 20"')

try {
    $hostArgs=$commonArgs + @('-cwhost',"-port=$loginPort",'-MULTIHOME=127.0.0.1',"-cwname=$hostName",('-abslog="'+$hostLog+'"'))
    $hostProcess=Start-Process -FilePath $enginePath -ArgumentList ($hostArgs -join ' ') -WindowStyle Hidden -PassThru
    $ownedProcesses += $hostProcess
    $hostProcess.PriorityClass='BelowNormal'
    Write-Output "Login host started: PID=$($hostProcess.Id), loopback UDP=$loginPort"
    $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while([DateTime]::UtcNow -lt $deadline){
        if($hostProcess.HasExited){throw 'The test host exited before opening its loopback listener.'}
        $hostText=Read-LoginLog $hostLog
        if($hostText -match "IpNetDriver listening on port $loginPort"){$hostReady=$true;break}
        Start-Sleep -Seconds 1
    }
    if(-not $hostReady){throw 'Timed out waiting for the dedicated loopback test listener.'}
    $hostNameInTravel=$hostText.Contains("mode=lobby?Name=$hostName")
    if(-not $hostNameInTravel){throw 'Host travel did not retain the requested Chinese nickname.'}

    $clientArgs=$commonArgs + @("-cwjoin=127.0.0.1:$loginPort",'-MULTIHOME=127.0.0.1',"-cwname=$clientName",('-abslog="'+$clientLog+'"'))
    $clientProcess=Start-Process -FilePath $enginePath -ArgumentList ($clientArgs -join ' ') -WindowStyle Hidden -PassThru
    $ownedProcesses += $clientProcess
    $clientProcess.PriorityClass='BelowNormal'
    Write-Output "Login client started: PID=$($clientProcess.Id)"
    while([DateTime]::UtcNow -lt $deadline){
        if($hostProcess.HasExited -or $clientProcess.HasExited){throw 'A test process exited before the host accepted the client nickname.'}
        $hostText=Read-LoginLog $hostLog
        $requestMatches=[regex]::Matches($hostText, '(?m)^.*LogNet: Join request: (?<url>[^\r\n]+)\r?$')
        foreach($match in $requestMatches){
            if($match.Groups['url'].Value -match ('(?:^|\?)Name='+[regex]::Escape($clientName)+'(?:\?|$)')){
                $requestEvidence=$match.Value.TrimEnd()
            }
        }
        $successMatches=[regex]::Matches($hostText, '(?m)^.*LogNet: Join succeeded: (?<name>[^\r\n]+)\r?$')
        foreach($match in $successMatches){
            if($match.Groups['name'].Value.Trim() -ceq $clientName){$successEvidence=$match.Value.TrimEnd()}
        }
        if($requestEvidence -and $successEvidence){$clientReceived=$true;break}
        if($hostText -match 'Fatal error:|Assertion failed:|Join failure:'){throw 'The host reported a runtime or login failure.'}
        Start-Sleep -Seconds 1
    }
    if(-not $clientReceived){throw 'Timed out waiting for host Join request and Join succeeded to contain the exact client nickname.'}
}
catch {
    $failures.Add($_.Exception.Message)
}
finally {
    # These process objects were returned by this script's two Start-Process calls.
    # Never enumerate or terminate unrelated Unreal instances, children, or ports.
    $processReports=@()
    foreach($ownedProcess in $ownedProcesses){
        $forced=$false
        try {
            if(-not $ownedProcess.HasExited){$ownedProcess.Kill();$ownedProcess.WaitForExit(10000) | Out-Null;$forced=$true}
            if(-not $ownedProcess.HasExited){$failures.Add("Owned test PID $($ownedProcess.Id) did not terminate.")}
            $processReports += @{pid=$ownedProcess.Id;terminated_after_check=$forced;exit_code=$(if($ownedProcess.HasExited){$ownedProcess.ExitCode}else{$null})}
        } catch {$failures.Add("Failed to stop owned test PID $($ownedProcess.Id): $($_.Exception.Message)")}
        finally {$ownedProcess.Dispose()}
    }
    $settingsAfter=Get-UserSettingsDigest
    $settingsUnchanged=($settingsBefore.Count -eq $settingsAfter.Count)
    foreach($key in $settingsBefore.Keys){
        if(-not $settingsAfter.ContainsKey($key) -or $settingsAfter[$key] -ne $settingsBefore[$key]){$settingsUnchanged=$false}
    }
    if(-not $settingsUnchanged){$failures.Add('GameUserSettings.ini changed during the check; inspect before/after hashes.')}
    @{
        passed=($clientReceived -and $failures.Count -eq 0)
        scope='Two local editor game processes; loopback login name receipt only; no ready, match, screenshots, or remote server.'
        started_utc=$started.ToString('o');finished_utc=[DateTime]::UtcNow.ToString('o')
        port=$loginPort;host_name=$hostName;client_name=$clientName
        host_listener_ready=$hostReady;host_name_in_travel=$hostNameInTravel
        client_name_received_by_host=$clientReceived
        join_request=$requestEvidence;join_succeeded=$successEvidence
        config_writes_disabled=$true;user_settings_unchanged=$settingsUnchanged
        user_settings_before=$settingsBefore;user_settings_after=$settingsAfter
        processes=$processReports;failures=@($failures);logs=@('host.log','client.log')
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $out 'report.json') -Encoding utf8
}
Write-Output "Login-name check finished: received=$clientReceived, failures=$($failures.Count), output=$out"
if($failures.Count){throw ($failures -join ' ')}
