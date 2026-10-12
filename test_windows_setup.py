# SPDX-License-Identifier: MIT
"""Exercise the installer's actual config-writing block without installing dependencies."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell installer')
class WindowsSetupTests(unittest.TestCase):
    def test_axr_template_preserves_private_windows_paths_and_manual_tool_scope(self):
        shell = shutil.which('pwsh') or shutil.which('powershell')
        if not shell:self.skipTest('PowerShell unavailable')
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(prefix="AXR 中文 $ ' ") as tmp:
            fixture = Path(tmp)
            shutil.copy2(root/'codex-axr.example.toml', fixture/'codex-axr.example.toml')
            env = dict(os.environ, AXR_FIXTURE_ROOT=str(fixture), AXR_SETUP_SOURCE=str(root/'setup.ps1'))
            script = r'''
$ErrorActionPreference = 'Stop'
$TaskTokens = $null; $TaskErrors = $null
$TaskAst = [System.Management.Automation.Language.Parser]::ParseFile($env:AXR_SETUP_SOURCE, [ref]$TaskTokens, [ref]$TaskErrors)
if ($TaskErrors.Count) { throw 'installer syntax invalid' }
$TaskBlocks = @($TaskAst.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Clauses[0].Item1.Extent.Text -eq '$AXR' -and
    $node.Clauses[0].Item2.Extent.Text.Contains('[IO.File]::WriteAllText')
}, $true))
if ($TaskBlocks.Count -ne 1) { throw 'installer output block missing' }
$TaskRoot = $env:AXR_FIXTURE_ROOT
$AXRState = Join-Path $TaskRoot "owner state $ '"
& ([scriptblock]::Create('& ' + $TaskBlocks[0].Clauses[0].Item2.Extent.Text))
'''
            subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', script],
                           env=env, check=True, capture_output=True, timeout=30)
            config = tomllib.loads((fixture/'codex-axr.toml').read_text(encoding='utf8'))
            server = config['mcp_servers']['wechat_axr']
            self.assertEqual(server['command'], str(fixture/'.venv'/'Scripts'/'python.exe'))
            self.assertEqual(server['cwd'], str(fixture))
            self.assertEqual(server['args'], [str(fixture/'server.py'), '--axr-state',
                                             str(fixture/"owner state $ '"), '--listener', '--manual-replies'])
            self.assertFalse(any('send' in tool or 'owner' in tool for tool in server['enabled_tools']))
            self.assertFalse((fixture/'config.json').exists())
            self.assertFalse((fixture/'codex-mcp.toml').exists())


if __name__ == '__main__':unittest.main()
