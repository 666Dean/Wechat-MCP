param([string]$PythonExe = "$PSScriptRoot\.venv\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw 'Run setup.ps1 first, or pass -PythonExe with your Python executable.'
}
Write-Host '请输入微信中的唯一备注名，一行一位；直接回车结束。'
Write-Host '此操作会替换整个主动代回复名单；不输入任何名字则清空名单。'
$TaskRemarkNames = @()
while ($true) {
    $TaskRemarkName = Read-Host '备注名'
    if ([string]::IsNullOrWhiteSpace($TaskRemarkName)) { break }
    $TaskRemarkNames += $TaskRemarkName.Trim()
}
& $PythonExe "$PSScriptRoot\server.py" --set-contacts @TaskRemarkNames
if ($LASTEXITCODE -ne 0) { throw 'Contact update failed.' }
Write-Host '如果 MCP 服务已在运行，请通过 set_reply_contacts 更改以立即生效；本脚本的更改需重启服务。'
