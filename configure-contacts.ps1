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
Write-Host '名单已保存。正在运行的服务会在下一次工具调用时自动加载，无需重启。'
