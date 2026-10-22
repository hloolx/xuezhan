# CivWar project helper (Windows PowerShell 5+ / PowerShell 7)
#
#   powershell -ExecutionPolicy Bypass -File Tools\civwar.ps1 <command> [options]
#
# Commands:
#   simtest              Build & run the engine-independent rules core tests (no Unreal needed)
#   build                Build the CivWarEditor target (Development, Win64)
#   content              Run Tools/setup_content.py in the editor (map, materials, data tables)
#   setup                build + content
#   editor               Open the project in Unreal Editor
#   run                  Start the game (standalone, main menu)
#   host                 Start the game and create a room automatically
#   join -Address <ip>   Start the game and join a room automatically
#   nettest              Two local instances auto-join, auto-play a full match, then compare results
#   package              Build a standalone Windows Shipping package into Build\Windows
#
# Engine location: -EngineRoot <path>, or env UE_ROOT, or the Epic Launcher registry entry for 5.8,
# or "C:\Program Files\Epic Games\UE_5.8".
param(
	[Parameter(Position = 0)][string]$Command = "help",
	[string]$EngineRoot = "",
	[string]$Address = "127.0.0.1",
	[int]$Matches = 20,
	[int]$TimeoutMinutes = 40,
	[ValidateSet("Shipping", "Development")][string]$Configuration = "Shipping",
	[string]$PackageDirectory = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

# UE on a non-English Windows code page cannot compile projects whose path contains non-ASCII characters
# (MSVC response files mangle the path). Build and launch through an ASCII directory junction instead.
function Get-AsciiProjectRoot {
	if ($Root -notmatch '[^\x00-\x7F]') { return $Root }
	$junction = Join-Path (Split-Path -Parent $Root) "CivWar"
	if (Test-Path $junction) {
		$item = Get-Item $junction
		$target = [string]($item.Target | Select-Object -First 1)
		if ($item.LinkType -eq "Junction" -and ($target.TrimEnd('\') -eq $Root.TrimEnd('\'))) { return $junction }
		throw "$junction exists but is not a junction to $Root. Rename it, or move the project to an ASCII-only path."
	}
	New-Item -ItemType Junction -Path $junction -Target $Root | Out-Null
	Write-Host "== Created ASCII junction $junction -> $Root (open the project from this path)"
	return $junction
}
$BuildRoot = Get-AsciiProjectRoot
$Root = $BuildRoot   # all paths handed to UE tools (scripts, logs, package output) use the ASCII path
$Project = Join-Path $BuildRoot "CivWar.uproject"

function Find-Engine {
	if ($EngineRoot -and (Test-Path $EngineRoot)) { return (Resolve-Path $EngineRoot).Path }
	if ($env:UE_ROOT -and (Test-Path $env:UE_ROOT)) { return $env:UE_ROOT }
	foreach ($key in @("HKLM:\SOFTWARE\EpicGames\Unreal Engine\5.8", "HKLM:\SOFTWARE\WOW6432Node\EpicGames\Unreal Engine\5.8")) {
		if (Test-Path $key) {
			$dir = (Get-ItemProperty $key).InstalledDirectory
			if ($dir -and (Test-Path $dir)) { return $dir }
		}
	}
	# Engines registered as custom builds (copied/unzipped engines, source builds): HKCU\...\Builds { GUID = path }
	$builds = "HKCU:\SOFTWARE\Epic Games\Unreal Engine\Builds"
	if (Test-Path $builds) {
		$props = Get-ItemProperty $builds
		foreach ($p in $props.PSObject.Properties) {
			if ($p.Name -like "PS*") { continue }
			$dir = [string]$p.Value
			$versionFile = Join-Path $dir "Engine\Build\Build.version"
			if ((Test-Path $versionFile)) {
				$v = Get-Content $versionFile -Raw | ConvertFrom-Json
				if ($v.MajorVersion -eq 5 -and $v.MinorVersion -eq 8) { return $dir }
			}
		}
	}
	$default = "C:\Program Files\Epic Games\UE_5.8"
	if (Test-Path $default) { return $default }
	throw "Unreal Engine 5.8 not found. Install it from the Epic Games Launcher, or pass -EngineRoot <path> / set UE_ROOT."
}

function Get-EditorExe($ue) { return Join-Path $ue "Engine\Binaries\Win64\UnrealEditor.exe" }
function Get-EditorCmdExe($ue) { return Join-Path $ue "Engine\Binaries\Win64\UnrealEditor-Cmd.exe" }

function Invoke-Build {
	$ue = Find-Engine
	$build = Join-Path $ue "Engine\Build\BatchFiles\Build.bat"
	Write-Host "== Building CivWarEditor with $ue"
	& $build CivWarEditor Win64 Development "-Project=$Project" -WaitMutex -FromMsBuild
	if ($LASTEXITCODE -ne 0) { throw "Build failed ($LASTEXITCODE)" }
}

function Invoke-Content {
	$ue = Find-Engine
	$script = Join-Path $Root "Tools\setup_content.py"
	Write-Host "== Generating editor content"
	& (Get-EditorCmdExe $ue) $Project -run=pythonscript "-script=$script" -unattended -nosplash -nop4 -stdout -DDC=InstalledNoZenLocalFallback
	if ($LASTEXITCODE -ne 0) { throw "Content setup failed ($LASTEXITCODE)" }
}

function Start-Game([string]$Extra, [string]$LogName, [int]$WinX = 40) {
	# The public source checkout excludes the author's private AI art assets.
	if (-not (Test-Path (Join-Path $Root "Content/ArtPilot"))) { $Extra = "-cwlegacyart $Extra" }
	$ue = Find-Engine
	$logDir = Join-Path $Root "Saved\Logs"
	New-Item -ItemType Directory -Force $logDir | Out-Null
	$log = Join-Path $logDir $LogName
	# This machine's Zen loopback service can time out; use the same local DDC graph as the verified captures.
	$argLine = "`"$Project`" -game -DDC=InstalledNoZenLocalFallback -windowed -ResX=1280 -ResY=720 -WinX=$WinX -WinY=60 -log `"-abslog=$log`" $Extra"
	Write-Host "== Starting: $argLine"
	return Start-Process -FilePath (Get-EditorExe $ue) -ArgumentList $argLine -PassThru
}

function Get-ResultLine([string]$LogPath) {
	if (-not (Test-Path $LogPath)) { return $null }
	$line = Select-String -Path $LogPath -Pattern "CIVWAR_RESULT" | Select-Object -Last 1
	if (-not $line) { return $null }
	$fields = @{}
	foreach ($pair in ($line.Line -split "CIVWAR_RESULT")[1].Trim().Split(" ")) {
		$kv = $pair.Split("=")
		if ($kv.Count -eq 2) { $fields[$kv[0]] = $kv[1] }
	}
	return $fields
}

function Invoke-NetTest {
	$logDir = Join-Path $Root "Saved\Logs"
	$hostLog = Join-Path $logDir "nettest_host.log"
	$clientLog = Join-Path $logDir "nettest_client.log"
	Remove-Item -ErrorAction SilentlyContinue $hostLog, $clientLog
	$h = Start-Game "-cwhost -cwautoready -cwautoplay -cwexitonend -cwname=Host" "nettest_host.log" 0
	Start-Sleep -Seconds 8
	$c = Start-Game "-cwjoin=127.0.0.1 -cwautoready -cwautoplay -cwcheattest -cwexitonend -cwname=Client" "nettest_client.log" 1300
	$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
	while ((-not $h.HasExited -or -not $c.HasExited) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 5 }
	if (-not $h.HasExited) { $h.Kill() }
	if (-not $c.HasExited) { $c.Kill() }

	$hr = Get-ResultLine $hostLog
	$cr = Get-ResultLine $clientLog
	if (-not $hr -or -not $cr) { throw "Missing CIVWAR_RESULT line (host=$([bool]$hr) client=$([bool]$cr)). See $hostLog / $clientLog" }
	$keys = @("winner", "reason", "base0", "base1", "age0", "age1", "trained0", "trained1", "kills0", "kills1")
	$mismatch = @()
	foreach ($k in $keys) { if ($hr[$k] -ne $cr[$k]) { $mismatch += "$k host=$($hr[$k]) client=$($cr[$k])" } }
	Write-Host "Host  : $(($keys | ForEach-Object { "$_=$($hr[$_])" }) -join ' ')"
	Write-Host "Client: $(($keys | ForEach-Object { "$_=$($cr[$_])" }) -join ' ')"
	$rej = Select-String -Path $clientLog -Pattern "CIVWAR_REJECTIONS" | Select-Object -Last 1
	if ($rej) { Write-Host "Client rejections (result:count): $($rej.Line.Split('client=')[-1])" }
	if ($mismatch.Count -gt 0) { throw "Host/client results differ: $($mismatch -join '; ')" }
	Write-Host "== NETTEST PASSED: both instances observed the same match result (local multi-instance only)"
}

function Invoke-Package {
	$ue = Find-Engine
	$uat = Join-Path $ue "Engine\Build\BatchFiles\RunUAT.bat"
	$out = Join-Path $Root "Build\Windows"
	if ($PackageDirectory) { $out = [IO.Path]::GetFullPath($PackageDirectory) }
	$appLocal = Join-Path $ue "Engine\Binaries\ThirdParty\AppLocalDependencies"
	if (-not (Test-Path (Join-Path $appLocal "Win64"))) { throw "App-local runtime dependencies missing: $appLocal" }
	& $uat BuildCookRun "-project=$Project" -noP4 -platform=Win64 "-clientconfig=$Configuration" -build -cook -stage -pak -iostore -compressed -prereqs -nodebuginfo -archive "-archivedirectory=$out" "-applocaldirectory=$appLocal" '-ubtargs=-MaxParallelActions=2 -NoUBA' '-AdditionalCookerOptions=-DDC=InstalledNoZenLocalFallback -SkipZenStore' -utf8output -unattended
	if ($LASTEXITCODE -ne 0) { throw "Package failed ($LASTEXITCODE)" }
	Write-Host "== Package written to $out"
}

switch ($Command.ToLower()) {
	"simtest" { & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "Tools\run_sim_tests.ps1") -Matches $Matches; exit $LASTEXITCODE }
	"build" { Invoke-Build }
	"content" { Invoke-Content }
	"setup" { Invoke-Build; Invoke-Content }
	"editor" { $ue = Find-Engine; Start-Process -FilePath (Get-EditorExe $ue) -ArgumentList "`"$Project`"" }
	"run" { Start-Game "" "game.log" | Out-Null }
	"host" { Start-Game "-cwhost -cwname=Host" "host.log" | Out-Null }
	"join" { Start-Game "-cwjoin=$Address -cwname=Guest" "join.log" 700 | Out-Null }
	"nettest" { Invoke-NetTest }
	"package" { Invoke-Package }
	default {
		Get-Content $PSCommandPath | Select-Object -Skip 1 -First 20 | ForEach-Object { $_.TrimStart("#") }
	}
}
