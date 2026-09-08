[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet('build','up','test','validate','shell','logs','down')]
    [string]$Command = 'test',
    [Parameter(Position=1)]
    [string]$Target,
    [Parameter(Position=2, ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs,
    [string]$ProjectRoot = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$resolvedProject = (Resolve-Path -LiteralPath $ProjectRoot).Path
$env:KICAD_PROJECT_DIR = $resolvedProject
$env:KICAD_ENTRYPOINT_PROJECT = if ($Target) { $Target } else { 'tests/fixtures/kicad-project/minimal.kicad_pcb' }
$env:KICAD_TEST_PROJECT = if ($Target) { $Target } else { 'tests/fixtures/kicad-project/minimal.kicad_pcb' }
$dockerConfig = Join-Path $env:TEMP 'kicad-automation-docker-config'
New-Item -ItemType Directory -Force -Path $dockerConfig | Out-Null
$env:DOCKER_CONFIG = $dockerConfig

function Invoke-Compose([string[]]$ComposeArgs) {
    & docker compose --project-directory $repoRoot -f (Join-Path $repoRoot 'compose.yaml') @ComposeArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE" }
}

switch ($Command) {
    'build'    { Invoke-Compose @('build','--pull','kicad') }
    'up'       { Invoke-Compose @('up','kicad') }
    'test'     { Invoke-Compose @('run','--rm','test') }
    'validate' { if (-not $Target) { throw 'validate requires a project path or stem' }; Invoke-Compose (@('run','--rm','kicad','validate','--project',"/workspace/$Target") + $ExtraArgs) }
    'shell'    { Invoke-Compose @('run','--rm','kicad','shell') }
    'logs'     { Invoke-Compose @('logs','kicad') }
    'down'     { Invoke-Compose @('down','--remove-orphans') }
}
