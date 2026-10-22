# Build and run the engine-independent rules core tests.
# Requires only the VS 2022 C++ toolchain and CMake (no Unreal Engine needed).
# Usage: powershell -ExecutionPolicy Bypass -File Tools/run_sim_tests.ps1 [-Matches 20] [-VerboseMatches]
param(
	[int]$Matches = 20,
	[switch]$VerboseMatches
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Src = Join-Path $Root "Tests/SimHarness"
$Build = Join-Path $Root "Intermediate/SimHarness"

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
	& python -I (Join-Path $Root "Tools/check_data_schema.py")
	if ($LASTEXITCODE -ne 0) { throw "Data schema check failed (Content/Data vs CWDataTypes.h)" }
} else {
	Write-Warning "python not found: skipping data schema check"
}

$cmake = Get-Command cmake -ErrorAction SilentlyContinue
if (-not $cmake) { throw "cmake not found: install CMake 3.20+ and add it to PATH" }

cmake -S $Src -B $Build -G "Visual Studio 17 2022" -A x64 | Out-Host
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed" }
cmake --build $Build --config Release | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Build failed" }

$exe = Join-Path $Build "Release/SimHarness.exe"
$argsList = @((Join-Path $Root "Content/Data"), "--matches", "$Matches")
if ($VerboseMatches) { $argsList += "--verbose" }
& $exe @argsList
exit $LASTEXITCODE
