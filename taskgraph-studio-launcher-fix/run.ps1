# Convenience launcher: prefers a regular Python install, then the Codex bundled runtime.
# All command arguments pass through, for example: ./run.ps1 run --contract example.json
$taskPython = Get-Command python -ErrorAction SilentlyContinue
if ($taskPython -and $taskPython.Source -notlike '*WindowsApps*') {
    & $taskPython.Source "$PSScriptRoot/cli.py" @args
    exit $LASTEXITCODE
}
$bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (Test-Path -LiteralPath $bundledPython) {
    & $bundledPython "$PSScriptRoot/cli.py" @args
    exit $LASTEXITCODE
}
Write-Error 'Install Python 3.11 or newer, then run python cli.py from this folder.'
exit 2
