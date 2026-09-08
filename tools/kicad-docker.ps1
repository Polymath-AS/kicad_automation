[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet('build','doctor','check','kibot','ibom','route','shell','versions','smoke','down')]
    [string]$Command = 'doctor',
    [Parameter(Position=1)]
    [string]$Target,
    [Parameter(Position=2, ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs,
    [string]$ProjectRoot = (Get-Location).Path,
    [ValidateRange(1,1000)]
    [int]$MaxPasses = 10,
    [ValidateRange(0,64)]
    [int]$OptimizerThreads = 0,
    [ValidateRange(10,3600)]
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$resolvedProject = (Resolve-Path -LiteralPath $ProjectRoot).Path
$env:KICAD_PROJECT_DIR = $resolvedProject
$dockerConfig = Join-Path $env:TEMP 'kicad-automation-docker-config'
New-Item -ItemType Directory -Force -Path $dockerConfig | Out-Null
$env:DOCKER_CONFIG = $dockerConfig

function Invoke-Compose([string[]]$ComposeArgs) {
    & docker compose --project-directory $repoRoot -f (Join-Path $repoRoot 'compose.yaml') @ComposeArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE" }
}

switch ($Command) {
    'build'    { Invoke-Compose @('build','--pull','kicad') }
    'doctor'   { Invoke-Compose @('run','--rm','kicad','doctor') }
    'check'    { if (-not $Target) { throw 'check requires the relative project path/stem' }; Invoke-Compose (@('run','--rm','kicad','check',$Target) + $ExtraArgs) }
    'kibot'    { if (-not $Target) { throw 'kibot requires a config path' }; Invoke-Compose (@('run','--rm','kicad','kibot',$Target) + $ExtraArgs) }
    'ibom'     { if (-not $Target) { throw 'ibom requires a board path' }; Invoke-Compose (@('run','--rm','kicad','ibom',$Target) + $ExtraArgs) }
    'shell'    { Invoke-Compose @('run','--rm','kicad','shell') }
    'versions' { Invoke-Compose @('run','--rm','kicad','doctor'); Invoke-Compose @('--profile','routing','run','--rm','freerouting','-help') }
    'route' {
        if (-not $Target) { throw 'route requires a DSN path relative to ProjectRoot' }
        $inputPath = $Target.Replace('\','/')
        if ($inputPath.StartsWith('/') -or $inputPath.Contains('..')) { throw 'Use a relative DSN path without ..' }
        if (-not (Test-Path -LiteralPath (Join-Path $resolvedProject $Target))) { throw "DSN not found: $Target" }
        $outputPath = if ($ExtraArgs.Count -gt 0 -and $ExtraArgs[0]) { $ExtraArgs[0].Replace('\','/') } else { [IO.Path]::ChangeExtension($inputPath,'.ses') }
        if ($outputPath.StartsWith('/') -or $outputPath.Contains('..')) { throw 'Use a relative SES path without ..' }
        $outputHost = Join-Path $resolvedProject $outputPath
        if (Test-Path -LiteralPath $outputHost) { throw "SES output already exists; choose a fresh path: $outputPath" }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputHost) | Out-Null
        Invoke-Compose @('--profile','routing','run','--rm','--entrypoint','timeout','freerouting','--signal=TERM','--kill-after=10s',"${TimeoutSeconds}s",'java','-jar','/app/freerouting-executable.jar','--gui.enabled=false','-da','-dl','-mp',"$MaxPasses",'-mt',"$OptimizerThreads",'-de',"/work/$inputPath",'-do',"/work/$outputPath")
        if (-not (Test-Path -LiteralPath $outputHost) -or (Get-Item -LiteralPath $outputHost).Length -eq 0) {
            throw "Freerouting completed without creating a non-empty SES file: $outputPath"
        }
        Write-Host "Created $outputHost"
    }
    'smoke' {
        Invoke-Compose @('build','--pull','kicad')
        Invoke-Compose @('run','--rm','kicad','doctor')
        Invoke-Compose @('--profile','routing','pull','freerouting')
        Invoke-Compose @('--profile','routing','run','--rm','freerouting','-help')
    }
    'down' { Invoke-Compose @('--profile','routing','down','--remove-orphans') }
}
