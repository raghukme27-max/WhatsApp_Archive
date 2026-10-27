param(
    [Parameter(Mandatory = $true)]
    [string] $InstallPath,
    [Parameter(Mandatory = $true)]
    [string] $DataPath,
    [Parameter(Mandatory = $true)]
    [string] $PythonExe
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common_windows.ps1")

try {
    $configPath = Join-Path $DataPath ".env"
    $environment = Import-ArchiveEnvironment -Path $configPath
    if (-not $environment.ContainsKey("STATE_DB_PATH") -or
        [string]::IsNullOrWhiteSpace([string]$environment["STATE_DB_PATH"])) {
        $env:STATE_DB_PATH = Join-Path $DataPath "state"
    }
    if (-not $environment.ContainsKey("WEBHOOK_HOST") -or
        [string]::IsNullOrWhiteSpace([string]$environment["WEBHOOK_HOST"])) {
        $env:WEBHOOK_HOST = "127.0.0.1"
    }
    if (-not $environment.ContainsKey("WEBHOOK_PORT") -or
        [string]::IsNullOrWhiteSpace([string]$environment["WEBHOOK_PORT"])) {
        $env:WEBHOOK_PORT = "8000"
    }

    Push-Location $InstallPath
    try {
        & $PythonExe -m whatsapp_archive
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
catch {
    [Console]::Error.WriteLine("WhatsApp Archive service launcher failed: {0}", $_.Exception.Message)
    exit 1
}
