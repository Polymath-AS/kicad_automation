[CmdletBinding()]
param(
    [Parameter(Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$McpArgs
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$client = Join-Path $repoRoot 'scripts\kicad_mcp_client.py'

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw 'Python 3 is required to run the KiCad MCP client.'
}

& $python.Source $client @McpArgs
exit $LASTEXITCODE
