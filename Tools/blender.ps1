param([Parameter(ValueFromRemainingArguments=$true)][string[]]$BlenderArgs)
$ErrorActionPreference = 'Stop'
$candidate = if ($env:BLENDER_EXE) { $env:BLENDER_EXE } else { 'C:\Users\12153\devtools\blender-5.2.2\Blender Foundation\Blender 5.2\blender.exe' }
if (-not (Test-Path -LiteralPath $candidate)) { throw 'Set BLENDER_EXE to your installed blender.exe.' }
& $candidate @BlenderArgs
exit $LASTEXITCODE
