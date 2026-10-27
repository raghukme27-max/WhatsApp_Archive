param(
    [string] $InstallPath = (Join-Path $env:ProgramFiles "WhatsApp Archive"),
    [string] $DataPath = (Join-Path $env:ProgramData "WhatsAppArchive"),
    [string] $ServiceName = "WhatsAppArchive"
)

$ErrorActionPreference = "Stop"

try {
    if ($env:OS -ne "Windows_NT") {
        throw "This uninstaller must be run on Windows."
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this uninstaller from an elevated PowerShell window (Run as administrator)."
    }

    if (Test-Path -LiteralPath $InstallPath) {
        if (-not (Test-Path -LiteralPath (Join-Path $InstallPath ".whatsapp-archive-install") -PathType Leaf)) {
            throw "Install directory is not marked as managed by this installer; refusing to delete $InstallPath."
        }
        $configurationPath = Join-Path $DataPath ".env"
        if (-not (Test-Path -LiteralPath $configurationPath -PathType Leaf)) {
            throw "Configuration is missing; refusing to remove an installation without verifying the archive path."
        }
        . (Join-Path $PSScriptRoot "common_windows.ps1")
        $configuration = Import-ArchiveEnvironment -Path $configurationPath
        $paths = Get-ArchivePathConfiguration -Environment $configuration -DataPath $DataPath
        Assert-DisjointDeploymentPaths -ArchivePath $paths.ArchivePath -StatePath $paths.StatePath -InstallPath $InstallPath -DataPath $DataPath
    }

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $nssmPath = Join-Path $InstallPath "tools\nssm.exe"
    if ($service) {
        if (-not (Test-Path -LiteralPath $nssmPath -PathType Leaf)) {
            throw "Cannot find the installed NSSM service wrapper at $nssmPath."
        }
        if ($service.Status -ne "Stopped") {
            Stop-Service -Name $ServiceName -Force
            $service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(360))
        }
        & $nssmPath remove $ServiceName confirm | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not remove service '$ServiceName'."
        }
        Write-Output "Removed Windows service: $ServiceName"
    }
    else {
        Write-Output "Windows service '$ServiceName' was not installed."
    }

    if (Test-Path -LiteralPath $InstallPath) {
        Remove-Item -LiteralPath $InstallPath -Recurse -Force
        Write-Output "Removed application, virtual environment, deployment scripts, and NSSM from: $InstallPath"
    }

    Write-Output "Preserved persistent configuration, logs, and SQLite state: $DataPath"
    Write-Output "Preserved configured archive directory and all archived documents."
    Write-Output "PASS: uninstall completed."
}
catch {
    [Console]::Error.WriteLine("UNINSTALL FAILED: {0}", $_.Exception.Message)
    exit 1
}
