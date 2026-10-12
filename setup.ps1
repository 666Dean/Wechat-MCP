param(
    [string]$PythonExe = '',
    [switch]$AXR,
    [string]$AXRState = '',
    [string]$Toolchain = '',
    [string]$OpenSSLRoot = ''
)
$ErrorActionPreference = 'Stop'
$TaskRoot = $PSScriptRoot
if (-not $AXR -and ($AXRState -or $Toolchain -or $OpenSSLRoot)) {
    throw '-AXRState, -Toolchain and -OpenSSLRoot require -AXR.'
}
if ($AXR) {
    if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) { throw 'AXR requires CMake 3.24+ and Visual Studio C++ build tools.' }
    if (-not $AXRState) { $AXRState = Join-Path $env:LOCALAPPDATA 'wechat-codex-mcp\axr-owner-state' }
    if ($AXRState -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+[\\/]?)') { throw '-AXRState must be an absolute private directory path.' }
    $AXRState = [IO.Path]::GetFullPath($AXRState)
    if ($Toolchain) { $Toolchain = (Resolve-Path -LiteralPath $Toolchain -ErrorAction Stop).Path }
    if ($OpenSSLRoot) { $OpenSSLRoot = (Resolve-Path -LiteralPath $OpenSSLRoot -ErrorAction Stop).Path }
}
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
try {
    $TaskOldCMakeArgs = $env:CMAKE_ARGS
    try {
        $TaskExtraCMake = @()
        if ($Toolchain) { $TaskExtraCMake += "-DCMAKE_TOOLCHAIN_FILE=`"$($Toolchain.Replace('\','/'))`"" }
        if ($OpenSSLRoot) { $TaskExtraCMake += "-DOPENSSL_ROOT_DIR=`"$($OpenSSLRoot.Replace('\','/'))`"" }
        if ($TaskExtraCMake.Count) { $env:CMAKE_ARGS = (@($TaskOldCMakeArgs) + $TaskExtraCMake) -join ' ' }
        & $PythonExe -m pip --python "$TaskRoot\.venv\Scripts\python.exe" install -r "$TaskRoot\$TaskRequirements"
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    } finally { $env:CMAKE_ARGS = $TaskOldCMakeArgs }
    if ($AXR) {
        & $PythonExe -m pip --python "$TaskRoot\.venv\Scripts\python.exe" install 'pybind11==3.0.1'
        if ($LASTEXITCODE -ne 0) { throw 'AXR build dependency installation failed.' }
        $TaskBuildArgs = @('scripts/build_axr.py', '--config', 'Release')
        if ($Toolchain) { $TaskBuildArgs += @('--toolchain', $Toolchain) }
        if ($OpenSSLRoot) { $TaskBuildArgs += @('--openssl', $OpenSSLRoot) }
        & "$TaskRoot\.venv\Scripts\python.exe" @TaskBuildArgs
        if ($LASTEXITCODE -ne 0) { throw 'AXR native helper build or CTest failed.' }
    }
} finally { Pop-Location }
if ($AXR) {
    $TaskPythonToml = ConvertTo-Json -InputObject "$TaskRoot\.venv\Scripts\python.exe" -Compress
    $TaskRootToml = ConvertTo-Json -InputObject $TaskRoot -Compress
    $TaskArgsToml = ConvertTo-Json -InputObject @("$TaskRoot\server.py", '--axr-state', $AXRState, '--listener', '--manual-replies') -Compress
    $TaskConfigText = Get-Content -LiteralPath "$TaskRoot\codex-axr.example.toml" -Raw
    $TaskConfigText = $TaskConfigText.Replace('"/path/to/wechat-codex-mcp/.venv/bin/python"', $TaskPythonToml)
    $TaskConfigText = $TaskConfigText.Replace('["/path/to/wechat-codex-mcp/server.py", "--axr-state", "/private/axr-owner-state", "--listener", "--manual-replies"]', $TaskArgsToml)
    $TaskConfigText = $TaskConfigText.Replace('"/path/to/wechat-codex-mcp"', $TaskRootToml)
    [IO.File]::WriteAllText("$TaskRoot\codex-axr.toml", $TaskConfigText, [Text.UTF8Encoding]::new($false))
    Write-Output "AXR installed. MCP configuration: $TaskRoot\codex-axr.toml"
    Write-Output 'Initialize the owner state and grants locally before starting MCP. See docs/WINDOWS_UPDATE.md.'
    return
}
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
