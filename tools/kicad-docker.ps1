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
$defaultTarget = 'tests/fixtures/kicad-project/minimal.kicad_pcb'

function Get-ProjectRelativePath([string]$Root, [string]$Path) {
    $rootUri = New-Object System.Uri -ArgumentList (($Root.TrimEnd('\') + '\'))
    $pathUri = New-Object System.Uri -ArgumentList $Path
    [Uri]::UnescapeDataString($rootUri.MakeRelativeUri($pathUri).ToString()).Replace('/', '\')
}

function Resolve-KiCadTarget([string]$Root, [string]$RequestedTarget) {
    $targetPath = if ([IO.Path]::IsPathRooted($RequestedTarget)) {
        [IO.Path]::GetFullPath($RequestedTarget)
    } else {
        [IO.Path]::GetFullPath((Join-Path $Root $RequestedTarget))
    }

    if (Test-Path -LiteralPath $targetPath -PathType Container) {
        $projectName = Split-Path -Leaf $targetPath
        $boardPath = Join-Path $targetPath "$projectName.kicad_pcb"
        if (-not (Test-Path -LiteralPath $boardPath -PathType Leaf)) {
            $boards = @(Get-ChildItem -LiteralPath $targetPath -Filter '*.kicad_pcb' -File)
            if ($boards.Count -eq 1) {
                $boardPath = $boards[0].FullName
            } else {
                throw "KiCad project preflight failed: target directory '$targetPath' does not contain '$projectName.kicad_pcb' and does not have exactly one board file. ProjectRoot='$Root'."
            }
        }
    } else {
        $extension = [IO.Path]::GetExtension($targetPath).ToLowerInvariant()
        $stem = switch ($extension) {
            '.kicad_pcb' { $targetPath.Substring(0, $targetPath.Length - 10) }
            '.kicad_sch' { $targetPath.Substring(0, $targetPath.Length - 10) }
            '.kicad_pro' { $targetPath.Substring(0, $targetPath.Length - 10) }
            default { $targetPath }
        }
        $boardPath = "$stem.kicad_pcb"
    }

    $boardPath = [IO.Path]::GetFullPath($boardPath)
    $stemPath = $boardPath.Substring(0, $boardPath.Length - 10)
    $required = @("$stemPath.kicad_pro", "$stemPath.kicad_sch", $boardPath)
    $outside = $false
    try {
        $relativeBoard = Get-ProjectRelativePath $Root $boardPath
        $outside = $relativeBoard -eq '..' -or $relativeBoard.StartsWith("..$([IO.Path]::DirectorySeparatorChar)") -or [IO.Path]::IsPathRooted($relativeBoard)
    } catch {
        $outside = $true
    }
    if ($outside) {
        throw "KiCad project preflight failed: selected target '$RequestedTarget' resolves outside ProjectRoot '$Root'."
    }

    $missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
    if ($missing.Count -gt 0) {
        $missingText = ($missing -join ', ')
        $relative = (Get-ProjectRelativePath $Root $boardPath).Replace('\', '/')
        throw "KiCad project preflight failed: selected project is missing required file(s): $missingText. Host target='$boardPath'; container target='/workspace/$relative'; ProjectRoot='$Root'."
    }

    $relativeBoard = (Get-ProjectRelativePath $Root $boardPath).Replace('\', '/')
    [PSCustomObject]@{
        HostBoard = $boardPath
        HostStem = $stemPath
        ContainerBoard = $relativeBoard
        ContainerStem = $relativeBoard.Substring(0, $relativeBoard.Length - 10)
    }
}

$env:KICAD_PROJECT_DIR = $resolvedProject
$env:KICAD_ENTRYPOINT_PROJECT = $defaultTarget
$env:KICAD_TEST_PROJECT = $defaultTarget

if ($Command -in @('up', 'test', 'validate')) {
    if ($Command -eq 'validate' -and -not $Target) { throw 'validate requires a project path or stem' }
    $requestedTarget = if ($Target) { $Target } else { $defaultTarget }
    $resolvedTarget = Resolve-KiCadTarget $resolvedProject $requestedTarget
    $env:KICAD_ENTRYPOINT_PROJECT = $resolvedTarget.ContainerBoard
    $env:KICAD_TEST_PROJECT = $resolvedTarget.ContainerBoard
}

$dockerConfig = Join-Path $env:TEMP 'kicad-automation-docker-config'
New-Item -ItemType Directory -Force -Path $dockerConfig | Out-Null
$env:DOCKER_CONFIG = $dockerConfig

function Get-SafeComposeOutput([object[]]$Lines) {
    $token = [string]$env:KICAD_MCP_AUTH_TOKEN
    foreach ($line in $Lines) {
        $text = [string]$line
        if ($token) { $text = $text.Replace($token, '<redacted>') }
        $text
    }
}

function Get-ComposeFailureClass([string]$Output) {
    if ($Output -match '(?i)live schematic IPC is not supported|schematic.*IPC.*unavailable') {
        return 'unsupported_schematic_capability'
    }
    if ($Output -match '(?i)docker daemon|cannot connect|named pipe|access is denied|permission denied|is the docker engine running') {
        return 'docker_access_or_connectivity'
    }
    if ($Output -match '(?i)preflight|missing required|board not found|schematic not found|project not found|selected project is incomplete') {
        return 'project_files_or_selection'
    }
    if ($Output -match '(?i)erc|drc|validator|kicad-cli|results') {
        return 'validator_execution_or_design_result'
    }
    return 'compose_execution'
}

function Invoke-Compose([string[]]$ComposeArgs) {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& docker compose --project-directory $repoRoot -f (Join-Path $repoRoot 'compose.yaml') @ComposeArgs 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    $safeOutput = @(Get-SafeComposeOutput $output)
    if ($safeOutput.Count -gt 0) { $safeOutput | Write-Output }
    if ($exitCode -ne 0) {
        $failureDir = Join-Path $repoRoot '.kicad-automation\compose-failures'
        New-Item -ItemType Directory -Force -Path $failureDir | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $failureLog = Join-Path $failureDir "$stamp-$($Command).log"
        @(
            "command=$Command"
            "exit_code=$exitCode"
            "failure_class=$(Get-ComposeFailureClass ($safeOutput -join [Environment]::NewLine))"
            "project_root=$resolvedProject"
            "container_mount=/workspace"
            ''
            $safeOutput
        ) | Set-Content -LiteralPath $failureLog -Encoding utf8
        throw "Docker Compose failed with exit code $exitCode; classified as $(Get-ComposeFailureClass ($safeOutput -join [Environment]::NewLine)). Output preserved at $failureLog"
    }
}

switch ($Command) {
    'build'    { Invoke-Compose @('build','--pull','kicad') }
    'up'       { Invoke-Compose @('up','kicad') }
    'test'     { Invoke-Compose @('run','--rm','-T','test') }
    'validate' { Invoke-Compose (@('run','--rm','-T','kicad','validate','--project',"/workspace/$($resolvedTarget.ContainerStem)") + $ExtraArgs) }
    'shell'    { Invoke-Compose @('run','--rm','kicad','shell') }
    'logs'     { Invoke-Compose @('logs','kicad') }
    'down'     { Invoke-Compose @('down','--remove-orphans') }
}
