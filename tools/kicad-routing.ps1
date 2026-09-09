[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet('build','doctor','run','mcp')]
    [string]$Command = 'doctor',
    [Parameter(Position=1)]
    [string]$Plan,
    [string]$ProjectRoot = (Get-Location).Path
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$env:KICAD_PROJECT_DIR = (Resolve-Path -LiteralPath $ProjectRoot).Path
$env:KICAD_ROUTING_JOBS_DIR = Join-Path $repoRoot '.kicad-automation\routing'
New-Item -ItemType Directory -Force -Path $env:KICAD_ROUTING_JOBS_DIR | Out-Null
$compose = Join-Path $repoRoot 'compose.routing.yaml'
if ($Command -eq 'build') {
    & docker compose --project-directory $repoRoot -f (Join-Path $repoRoot 'compose.yaml') build kicad
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & docker compose --project-directory $repoRoot -f $compose build routing
} else {
    $routingArgs = @('run', '--rm', '-T', '--no-deps', 'routing', $Command)
    if ($Command -eq 'run') {
        if (-not $Plan) { throw 'run requires a workspace-relative routing plan JSON path' }
        $routingArgs += $Plan.Replace('\', '/')
    }
    & docker compose --project-directory $repoRoot -f $compose @routingArgs
}
exit $LASTEXITCODE
