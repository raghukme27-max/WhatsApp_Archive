param(
    [string] $SourcePath = (Split-Path -Parent $PSScriptRoot),
    [string] $InstallPath = (Join-Path $env:ProgramFiles "WhatsApp Archive"),
    [string] $DataPath = (Join-Path $env:ProgramData "WhatsAppArchive"),
    [string] $ServiceName = "WhatsAppArchive",
    [string] $PythonExe,
    [string] $NssmPath
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common_windows.ps1")

function Invoke-Nssm {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)
    & $script:NssmPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "NSSM command failed with exit code $LASTEXITCODE."
    }
}

function Resolve-PythonExecutable {
    param([string] $RequestedPath)

    $candidates = @()
    if ($RequestedPath) {
        $candidates += $RequestedPath
    }
    else {
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) {
            $resolved = & $launcher.Source -3 -c "import sys; print(sys.executable)"
            if ($LASTEXITCODE -eq 0 -and $resolved) {
                $candidates += $resolved | Select-Object -First 1
            }
        }
        foreach ($name in @("python.exe", "python3.exe")) {
            $command = Get-Command $name -ErrorAction SilentlyContinue
            if ($command) {
                $candidates += $command.Source
            }
        }
    }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $versionOutput = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}'); print(sys.executable)"
        if ($LASTEXITCODE -ne 0 -or @($versionOutput).Count -lt 2) {
            continue
        }
        $version = [version]$versionOutput[0]
        if ($version -ge [version]"3.11" -and $version -lt [version]"4.0") {
            $resolvedPath = [System.IO.Path]::GetFullPath([string]$versionOutput[1])
            if ($resolvedPath -match '(?i)^[A-Z]:\\Users\\[^\\]+\\') {
                throw "Python is installed in a user profile and may be unavailable to the LocalService account. Install Python for all users and pass its machine-wide executable path."
            }
            return $resolvedPath
        }
    }
    throw "Python 3.11 or newer (below 4.0) was not found. Install Python or pass -PythonExe with its full path."
}

try {
    if ($env:OS -ne "Windows_NT") {
        throw "This installer must be run on Windows 10 or Windows 11."
    }
    $os = Get-CimInstance -ClassName Win32_OperatingSystem
    if ($os.Caption -notmatch "Windows 10|Windows 11" -or [version]$os.Version -lt [version]"10.0") {
        throw "Unsupported Windows version: $($os.Caption) $($os.Version). Windows 10/11 is required."
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this installer from an elevated PowerShell window (Run as administrator)."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $SourcePath "whatsapp_archive\__main__.py") -PathType Leaf)) {
        throw "Application source not found under $SourcePath."
    }
    Assert-AbsoluteWindowsPath -Path $InstallPath -Name "InstallPath"
    Assert-AbsoluteWindowsPath -Path $DataPath -Name "DataPath"

    $PythonExe = Resolve-PythonExecutable -RequestedPath $PythonExe
    Write-Output "PASS: Windows 10/11 and Python $PythonExe verified."

    New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
    New-Item -ItemType Directory -Path $DataPath -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $DataPath "logs") -Force | Out-Null

    $installedNssm = Join-Path $InstallPath "tools\nssm.exe"
    if (-not $NssmPath -and (Test-Path -LiteralPath $installedNssm -PathType Leaf)) {
        $NssmPath = $installedNssm
    }
    if (-not $NssmPath) {
        $nssmCommand = Get-Command nssm.exe -ErrorAction SilentlyContinue
        if ($nssmCommand) {
            $NssmPath = $nssmCommand.Source
        }
    }
    if (-not $NssmPath -or -not (Test-Path -LiteralPath $NssmPath -PathType Leaf)) {
        throw "NSSM 2.24 is required. Obtain the official Windows x64 nssm.exe and pass -NssmPath <full path>."
    }
    $nssmVersion = & $NssmPath version 2>&1
    if ($LASTEXITCODE -ne 0 -or ($nssmVersion -join "`n") -notmatch "2\.24") {
        throw "NSSM 2.24 is required; the supplied service wrapper did not report that version."
    }

    $existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $markerPath = Join-Path $InstallPath ".whatsapp-archive-install"
    if ($existingService -and -not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "Service '$ServiceName' already exists but is not marked as managed by this installer; refusing to replace it."
    }

    $configPath = Join-Path $DataPath ".env"
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        $sourceConfig = Join-Path $SourcePath ".env"
        if (Test-Path -LiteralPath $sourceConfig -PathType Leaf) {
            Copy-Item -LiteralPath $sourceConfig -Destination $configPath
        }
        else {
            $examplePath = Join-Path $SourcePath ".env.example"
            if (-not (Test-Path -LiteralPath $examplePath -PathType Leaf)) {
                throw "Neither .env nor .env.example exists in $SourcePath."
            }
            $template = Get-Content -LiteralPath $examplePath -Raw
            $template = [regex]::Replace($template, "(?m)^ARCHIVE_PATH=.*$", "ARCHIVE_PATH=C:\EducationalArchive")
            $template = [regex]::Replace($template, "(?m)^STATE_DB_PATH=.*$", "STATE_DB_PATH=$DataPath\state")
            $template = [regex]::Replace($template, "(?m)^WEBHOOK_HOST=.*$", "WEBHOOK_HOST=127.0.0.1")
            Set-Content -LiteralPath $configPath -Value $template -Encoding UTF8
            throw "Created $configPath from the example. Edit ARCHIVE_PATH and WHATSAPP_VERIFY_TOKEN (and credentials when using live mode), then rerun the installer."
        }
    }

    $configuration = Import-ArchiveEnvironment -Path $configPath
    $paths = Get-ArchivePathConfiguration -Environment $configuration -DataPath $DataPath
    Assert-DisjointDeploymentPaths -ArchivePath $paths.ArchivePath -StatePath $paths.StatePath -InstallPath $InstallPath -DataPath $DataPath
    Write-Output "PASS: deployment configuration validated (secret values are not displayed)."

    New-Item -ItemType Directory -Path $paths.ArchivePath -Force | Out-Null
    New-Item -ItemType Directory -Path $paths.StatePath -Force | Out-Null
    $probePath = Join-Path $paths.ArchivePath (".install-check-{0}.tmp" -f [Guid]::NewGuid())
    [System.IO.File]::WriteAllText($probePath, "archive install check")
    Remove-Item -LiteralPath $probePath -Force
    Write-Output "PASS: configured archive location is writable."

    Set-ReadOnlyDirectoryAcl -Path $InstallPath
    Set-DirectoryAcl -Path $DataPath
    Set-DirectoryAcl -Path (Join-Path $DataPath "logs")
    Set-DirectoryAcl -Path $paths.ArchivePath
    Set-DirectoryAcl -Path $paths.StatePath
    & icacls.exe $configPath /inheritance:r /grant "BUILTIN\Administrators:F" "NT AUTHORITY\SYSTEM:F" "NT AUTHORITY\LOCAL SERVICE:R" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not restrict access to the deployment .env file."
    }

    if ($existingService) {
        if ($existingService.Status -ne "Stopped") {
            Stop-Service -Name $ServiceName -Force
            $existingService.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(360))
        }
        & $NssmPath remove $ServiceName confirm | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not remove the existing managed service."
        }
    }

    $packagePath = Join-Path $SourcePath "whatsapp_archive"
    Copy-Item -LiteralPath $packagePath -Destination $InstallPath -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $SourcePath "pyproject.toml") -Destination $InstallPath -Force
    $scriptsPath = Join-Path $InstallPath "scripts"
    New-Item -ItemType Directory -Path $scriptsPath -Force | Out-Null
    foreach ($scriptName in @("common_windows.ps1", "run_service.ps1", "health_check.ps1")) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $scriptName) -Destination $scriptsPath -Force
    }

    $toolsPath = Join-Path $InstallPath "tools"
    New-Item -ItemType Directory -Path $toolsPath -Force | Out-Null
    if ([System.IO.Path]::GetFullPath($NssmPath) -ne [System.IO.Path]::GetFullPath($installedNssm)) {
        Copy-Item -LiteralPath $NssmPath -Destination $installedNssm -Force
    }
    $script:NssmPath = $installedNssm

    $venvPython = Join-Path $InstallPath ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        & $PythonExe -m venv (Join-Path $InstallPath ".venv")
        if ($LASTEXITCODE -ne 0) {
            throw "Python virtual environment creation failed (exit code $LASTEXITCODE)."
        }
    }
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Virtual environment did not create its Python executable."
    }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime dependency validation failed."
    }
    Write-Output "PASS: isolated Python environment created and runtime dependencies verified."

    Set-Content -LiteralPath $markerPath -Value "Managed by scripts/install_windows.ps1" -Encoding ASCII
    $runnerPath = Join-Path $scriptsPath "run_service.ps1"
    $powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $parameters = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -InstallPath "{1}" -DataPath "{2}" -PythonExe "{3}"' -f $runnerPath, $InstallPath, $DataPath, $venvPython
    Invoke-Nssm -Arguments @("install", $ServiceName, $powershellPath, $parameters)
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppDirectory", $InstallPath)
    Invoke-Nssm -Arguments @("set", $ServiceName, "ObjectName", "NT AUTHORITY\LOCAL SERVICE", "")
    Invoke-Nssm -Arguments @("set", $ServiceName, "Start", "SERVICE_AUTO_START")
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppExit", "Default", "Restart")
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppRestartDelay", "5000")
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppStopMethodConsole", "300000")
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppStopMethodWindow", "1500")
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppStopMethodThreads", "1500")
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppKillProcessTree", "1")
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppStdout", (Join-Path $DataPath "logs\service-stdout.log"))
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppStderr", (Join-Path $DataPath "logs\service-stderr.log"))
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppRotateFiles", "1")
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppRotateOnline", "1")
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppRotateBytes", "10485760")
    & sc.exe failure $ServiceName reset= 86400 actions= "restart/5000/restart/15000/restart/60000"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not configure Windows Service Control Manager recovery actions."
    }
    & sc.exe failureflag $ServiceName 1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not configure service failure actions for non-crash exits."
    }

    Start-Service -Name $ServiceName
    (Get-Service -Name $ServiceName).WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
    & $powershellPath -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $scriptsPath "health_check.ps1") -InstallPath $InstallPath -DataPath $DataPath -ServiceName $ServiceName -PythonExe $venvPython
    if ($LASTEXITCODE -ne 0) {
        throw "Service started, but the deployment health check failed."
    }

    Write-Output "PASS: Windows service installed, configured for automatic restart, started, and passed health checks."
    Write-Output "Service: $ServiceName (LocalService account)"
    Write-Output "Application: $InstallPath"
    Write-Output "Persistent configuration/state/logs: $DataPath"
    Write-Output "Archive: $($paths.ArchivePath)"
}
catch {
    [Console]::Error.WriteLine("INSTALL FAILED: {0}", $_.Exception.Message)
    exit 1
}
