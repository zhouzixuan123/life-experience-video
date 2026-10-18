# Optional launcher. Use an explicit interpreter or the repository virtual environment.
$ErrorActionPreference = 'Stop'
$taskPythonBinary = $env:LIFE_VIDEO_PYTHON
if ([string]::IsNullOrWhiteSpace($taskPythonBinary)) {
    $taskPythonBinary = Join-Path $PSScriptRoot '../.venv/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath $taskPythonBinary -PathType Leaf)) {
    throw 'Create .venv first or set LIFE_VIDEO_PYTHON to your Python executable. See references/runtime.md.'
}
& $taskPythonBinary -B -s -X utf8 @args
exit $LASTEXITCODE
