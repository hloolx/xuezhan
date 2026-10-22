# Windows PowerShell 5.1+ / PowerShell 7. Local preparation only; never publishes to a server.
[CmdletBinding()]
param(
    [Parameter(Position=0)][ValidateSet('help','doctor','setup-streaming','signalling','stream-editor','stream-package','package','server')][string]$Command='help',
    [string]$EngineRoot='',
    [string]$InfrastructureRoot='',
    [string]$OutputRoot='',
    [string]$Executable='',
    [ValidateSet('Game','Server')][string]$Target='Game',
    [ValidateSet('Development','Shipping')][string]$Configuration='Development',
    [ValidateRange(1024,65535)][int]$PlayerPort=18080,
    [ValidateRange(1024,65535)][int]$StreamerPort=18888,
    [ValidateRange(1024,65535)][int]$GamePort=7777,
    [ValidateRange(640,3840)][int]$Width=1600,
    [ValidateRange(360,2160)][int]$Height=900,
    [string]$Proxy='',
    [switch]$DryRun
)
$ErrorActionPreference='Stop'
$ProjectRoot=Split-Path -Parent $PSScriptRoot

function Resolve-BuildRoot {
    if ($Command -eq 'doctor') { return $ProjectRoot }
    if ($ProjectRoot -notmatch '[^\x00-\x7F]') { return $ProjectRoot }
    $alias=Join-Path (Split-Path -Parent $ProjectRoot) 'CivWar'
    if (Test-Path -LiteralPath $alias) {
        $item=Get-Item -LiteralPath $alias
        $destination=[string]($item.Target | Select-Object -First 1)
        if ($item.LinkType -ne 'Junction' -or $destination.TrimEnd('\','/') -ne $ProjectRoot.TrimEnd('\','/')) {
            throw "Existing path is not this project's junction: $alias"
        }
    } elseif (!$DryRun) {
        New-Item -ItemType Junction -Path $alias -Target $ProjectRoot | Out-Null
    }
    return $alias
}

function Resolve-Engine {
    $candidates=@($EngineRoot, $env:UE_ROOT)
    $association=(Get-Content (Join-Path $ProjectRoot 'CivWar.uproject') -Raw | ConvertFrom-Json).EngineAssociation
    $registry='HKCU:\SOFTWARE\Epic Games\Unreal Engine\Builds'
    if (Test-Path $registry) {
        $entry=(Get-ItemProperty $registry).PSObject.Properties[$association]
        if ($entry) { $candidates += [string]$entry.Value }
    }
    $candidates += @('G:\epic\UE_5.8','C:\Program Files\Epic Games\UE_5.8')
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path (Join-Path $candidate 'Engine\Build\Build.version'))) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw 'UE not found. Use -EngineRoot or UE_ROOT.'
}

function Show-Invocation([string]$File, [string[]]$Arguments) {
    Write-Host ('& "{0}" {1}' -f $File, (($Arguments | ForEach-Object { '"' + $_ + '"' }) -join ' '))
}
function Invoke-Checked([string]$File, [string[]]$Arguments) {
    Show-Invocation $File $Arguments
    if ($DryRun) { return }
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File failed (exit $LASTEXITCODE)." }
}
function Invoke-NetworkChecked([string]$File, [string[]]$Arguments) {
    Show-Invocation $File $Arguments
    if ($DryRun) { return }
    & $File @Arguments
    if ($LASTEXITCODE -eq 0) { return }
    Write-Warning 'Network operation failed; retrying through HTTP proxy http://127.0.0.1:9000.'
    $env:HTTP_PROXY='http://127.0.0.1:9000'
    $env:HTTPS_PROXY='http://127.0.0.1:9000'
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File failed through proxy (exit $LASTEXITCODE)." }
}
function Start-LocalProcess([string]$File, [string[]]$Arguments) {
    Show-Invocation $File $Arguments
    if ($DryRun) { return }
    if (!(Test-Path -LiteralPath $File)) { throw "Executable missing: $File" }
    # Arguments originate in this script or validated paths; embedded quotes are rejected.
    if (($Arguments | Where-Object { $_.Contains('"') }).Count) { throw 'Quotes are not supported inside argument values.' }
    $line=($Arguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $process=Start-Process -FilePath $File -ArgumentList $line -WindowStyle Hidden -PassThru
    Write-Host "Started PID $($process.Id). Stop this process explicitly when the local test is finished."
}

if ($Command -eq 'help') {
    Write-Host @'
doctor                     Read local engine, GPU, plugin, and infrastructure readiness.
setup-streaming            Clone pinned UE5.8 infrastructure and build its reference frontend.
signalling                 Run loopback-only HTTP/WebSocket signalling (18080/18888), foreground.
stream-editor              Run standalone editor game with Pixel Streaming 2 (no compile).
stream-package -Executable Run an already packaged game with streaming.
package [-Target Server]   Build/cook/archive a Windows Game or Server package.
server -Executable        Run an already packaged dedicated server, explicit lobby map.
Every command accepts -DryRun. No command opens firewall rules or deploys remotely.
'@
    return
}

$BuildRoot=Resolve-BuildRoot
$Project=Join-Path $BuildRoot 'CivWar.uproject'
if (!$InfrastructureRoot) { $InfrastructureRoot=Join-Path $BuildRoot 'Saved\PixelStreamingInfrastructure' }
$InfrastructureRoot=[System.IO.Path]::GetFullPath($InfrastructureRoot)
$Pin='a5b526b2383110dcd84e6b56580bca8f459e1836'

switch ($Command) {
    'doctor' {
        $ue=Resolve-Engine
        $version=Get-Content (Join-Path $ue 'Engine\Build\Build.version') -Raw | ConvertFrom-Json
        $descriptor=Get-Content $Project -Raw | ConvertFrom-Json
        [pscustomobject]@{
            Engine=$ue; Version="$($version.MajorVersion).$($version.MinorVersion).$($version.PatchVersion)"
            InstalledBuild=(Test-Path (Join-Path $ue 'Engine\Build\InstalledBuild.txt'))
            Project=$Project
            PixelStreaming2Enabled=[bool]($descriptor.Plugins | Where-Object { $_.Name -eq 'PixelStreaming2' -and $_.Enabled })
            MapPresent=(Test-Path (Join-Path $BuildRoot 'Content\Maps\Battlefield.umap'))
            SignallingBuilt=(Test-Path (Join-Path $InfrastructureRoot 'Signalling\dist\cjs\pixelstreamingsignalling.js'))
            FrontendBuilt=(Test-Path (Join-Path $InfrastructureRoot 'SignallingWebServer\www\player.html'))
            Node=(Get-Command node -ErrorAction SilentlyContinue).Source
        } | Format-List
        Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion
        Write-Host 'InstalledBuild=True requires a source/server-enabled engine for the Server target. GPU names do not prove encoder compatibility.'
        Write-Host 'Streaming also requires explicitly enabling PixelStreaming2 in CivWar.uproject (Editor: Edit > Plugins), then rebuilding/restarting. This script does not change project plugins.'
    }
    'setup-streaming' {
        if ($Proxy) { $env:HTTP_PROXY=$Proxy; $env:HTTPS_PROXY=$Proxy }
        if (!(Test-Path -LiteralPath $InfrastructureRoot)) {
            Invoke-NetworkChecked 'git' @('clone','--depth','1','--branch','UE5.8','https://github.com/EpicGamesExt/PixelStreamingInfrastructure.git',$InfrastructureRoot)
        }
        if ($DryRun) { Write-Host "Would verify/fetch pinned commit $Pin and npm ci/build selected workspaces in $InfrastructureRoot"; return }
        Push-Location $InfrastructureRoot
        try {
            $actual=(& git rev-parse HEAD).Trim()
            if ($actual -ne $Pin) {
                if (& git status --porcelain) { throw 'Infrastructure has local changes; will not switch its commit.' }
                Invoke-NetworkChecked 'git' @('fetch','--depth','1','origin',$Pin)
                Invoke-Checked 'git' @('checkout','--detach',$Pin)
            }
            Invoke-NetworkChecked 'npm.cmd' @('ci','--workspace','Common','--workspace','Signalling','--workspace','SignallingWebServer','--workspace','Frontend/library','--workspace','Frontend/ui-library','--workspace','Frontend/implementations/typescript','--include-workspace-root','--no-audit','--no-fund')
            $oldWebpack=$env:WEBPACK_OUTPUT_PATH
            try {
                $env:WEBPACK_OUTPUT_PATH=Join-Path $InfrastructureRoot 'SignallingWebServer\www'
                Invoke-Checked 'npm.cmd' @('run','build:all:cjs')
            } finally { $env:WEBPACK_OUTPUT_PATH=$oldWebpack }
        } finally { Pop-Location }
        Write-Host 'Infrastructure prepared. Before streaming, manually enable PixelStreaming2 in CivWar.uproject and rebuild/restart the game. No UE process was started.'
    }
    'signalling' {
        if ($PlayerPort -eq $StreamerPort) { throw 'Player and streamer ports must differ.' }
        Invoke-Checked 'node' @((Join-Path $BuildRoot 'Deploy\local-signalling.cjs'),$InfrastructureRoot,[string]$PlayerPort,[string]$StreamerPort)
    }
    { $_ -in 'stream-editor','stream-package' } {
        $descriptor=Get-Content $Project -Raw | ConvertFrom-Json
        if (!($descriptor.Plugins | Where-Object { $_.Name -eq 'PixelStreaming2' -and $_.Enabled })) {
            $message='PixelStreaming2 is not enabled in CivWar.uproject. Enable it explicitly in Edit > Plugins, then rebuild/restart or repackage before streaming.'
            if ($DryRun) { Write-Warning $message } else { throw $message }
        }
        $argsList=@()
        if ($Command -eq 'stream-editor') {
            $ue=Resolve-Engine
            $Executable=Join-Path $ue 'Engine\Binaries\Win64\UnrealEditor.exe'
            $argsList += @($Project,'-game')
        } elseif (!$Executable) { throw 'Supply -Executable with the packaged CivWar.exe path.' }
        $logDirectory=Join-Path $BuildRoot 'Saved\Logs'
        if (!$DryRun) { New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null }
        $argsList += @("-PixelStreamingConnectionURL=ws://127.0.0.1:$StreamerPort",'-PixelStreamingID=CivWar','-PixelStreamingEncoderCodec=H264','-PixelStreamingWebRTCFps=30','-ExecCmds=t.MaxFPS 30','-RenderOffscreen','-ForceRes',"-ResX=$Width","-ResY=$Height",'-AudioMixer','-Unattended','-nosplash','-FullStdOutLogOutput',"-abslog=$(Join-Path $logDirectory 'pixel-streaming-game.log')")
        Start-LocalProcess $Executable $argsList
    }
    'package' {
        $ue=Resolve-Engine
        if ($Target -eq 'Server' -and (Test-Path (Join-Path $ue 'Engine\Build\InstalledBuild.txt'))) {
            throw 'Dedicated Server needs a source/server-enabled engine. This installed engine is not accepted. Use -EngineRoot with a source build.'
        }
        if (!$OutputRoot) { $OutputRoot=Join-Path $BuildRoot ("Build\Release\{0}-{1}-{2}" -f $Target,$Configuration,(Get-Date -Format 'yyyyMMdd-HHmmss')) }
        $OutputRoot=[System.IO.Path]::GetFullPath($OutputRoot)
        if (Test-Path -LiteralPath $OutputRoot) { throw "Output already exists; select a new -OutputRoot: $OutputRoot" }
        $uat=Join-Path $ue 'Engine\Build\BatchFiles\RunUAT.bat'
        $uatArgs=@('BuildCookRun',"-project=$Project",'-noP4','-platform=Win64',"-clientconfig=$Configuration",'-build','-cook','-stage','-pak','-iostore','-archive',"-archivedirectory=$OutputRoot",'-map=/Game/Maps/Battlefield','-utf8output','-unattended')
        if ($Target -eq 'Server') { $uatArgs += @('-server','-noclient','-serverplatform=Win64',"-serverconfig=$Configuration") }
        Invoke-Checked $uat $uatArgs
        if (!$DryRun) { Write-Host "UAT completed. Package location: $OutputRoot. Runtime/network acceptance is still required." }
    }
    'server' {
        if (!$Executable) { throw 'Supply -Executable with CivWarServer.exe from a successful Server package.' }
        Start-LocalProcess $Executable @('/Game/Maps/Battlefield?mode=lobby',"-port=$GamePort",'-unattended','-nullrhi','-nosound','-stdout','-FullStdOutLogOutput')
    }
}
