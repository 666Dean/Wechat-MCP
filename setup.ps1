param([string]$PythonExe = '', [switch]$AXR)
$ErrorActionPreference = 'Stop'
$TaskRoot = $PSScriptRoot
if (-not $PythonExe) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $PythonExe = (& py -3.12 -c 'import sys; print(sys.executable)').Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 x64 or provide -PythonExe.' }
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $PythonExe = (Get-Command python).Source
    } else { throw 'Install Python 3.12 x64 or provide -PythonExe.' }
}
& $PythonExe -c 'import sys; assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32, "Python 3.12 x64 required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 is required by the pinned Windows dependency.' }
& $PythonExe -m venv --without-pip "$TaskRoot\.venv"
if ($LASTEXITCODE -ne 0) { throw 'Could not create virtual environment. Use Python 3.12 x64.' }
$TaskRequirements = if ($AXR) { 'requirements.axr.txt' } else { 'requirements.txt' }
Push-Location -LiteralPath $TaskRoot
try { & $PythonExe -m pip --python "$TaskRoot\.venv\Scripts\python.exe" install -r "$TaskRoot\$TaskRequirements" }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not (Test-Path -LiteralPath "$TaskRoot\config.json")) {
    Copy-Item -LiteralPath "$TaskRoot\config.example.json" -Destination "$TaskRoot\config.json"
}
$TaskRootForward = $TaskRoot.Replace('\','/')
$TaskConfigText = @"
[mcp_servers.wechat-personal]
command = "$TaskRootForward/.venv/Scripts/python.exe"
args = ["$TaskRootForward/server.py"]
cwd = "$TaskRootForward"
startup_timeout_sec = 20
tool_timeout_sec = 60
"@
$TaskConfigText | Set-Content -LiteralPath "$TaskRoot\codex-mcp.toml" -Encoding utf8
Write-Output "Installed. MCP configuration: $TaskRoot\codex-mcp.toml"
