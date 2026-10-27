param(
    [string] $InstallPath = (Join-Path $env:ProgramFiles "WhatsApp Archive"),
    [string] $DataPath = (Join-Path $env:ProgramData "WhatsAppArchive"),
    [string] $ServiceName = "WhatsAppArchive",
    [string] $PythonExe
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common_windows.ps1")

try {
    $service = Get-Service -Name $ServiceName -ErrorAction Stop
    if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running) {
        throw "Windows service '$ServiceName' is $($service.Status), not Running."
    }
    $serviceDetails = Get-CimInstance -ClassName Win32_Service -Filter "Name='$ServiceName'"
    if ($serviceDetails.StartName -notmatch "(?i)(LOCAL SERVICE|LOCALSERVICE)$") {
        throw "Windows service is not configured to run as the expected LocalService account."
    }
    Write-Output "PASS: Windows service is running."

    $configuration = Import-ArchiveEnvironment -Path (Join-Path $DataPath ".env")
    $paths = Get-ArchivePathConfiguration -Environment $configuration -DataPath $DataPath
    Assert-DisjointDeploymentPaths -ArchivePath $paths.ArchivePath -StatePath $paths.StatePath -InstallPath $InstallPath -DataPath $DataPath
    $uri = "http://{0}:{1}/health" -f $paths.WebhookHost, $paths.WebhookPort
    $health = Invoke-RestMethod -Uri $uri -Method Get -TimeoutSec 5
    if ($health.status -ne "ok") {
        throw "The application health endpoint returned an unexpected response."
    }
    Write-Output "PASS: /health returned OK."

    if (-not (Test-Path -LiteralPath $paths.ArchivePath -PathType Container)) {
        throw "Configured archive directory is missing: $($paths.ArchivePath)"
    }
    $serviceSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-19")
    foreach ($directory in @($paths.ArchivePath, $paths.StatePath)) {
        $permissions = (Get-Acl -LiteralPath $directory).Access
        $serviceModify = $false
        foreach ($permission in $permissions) {
            try {
                $permissionSid = $permission.IdentityReference.Translate([Security.Principal.SecurityIdentifier])
            }
            catch {
                continue
            }
            if ($permissionSid.Value -eq $serviceSid.Value -and
                $permission.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow -and
                ($permission.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::Modify) -ne 0) {
                $serviceModify = $true
                break
            }
        }
        if (-not $serviceModify) {
            throw "The LocalService account does not have modify permission on $directory."
        }
    }
    $probePath = Join-Path $paths.ArchivePath (".health-check-{0}.tmp" -f [Guid]::NewGuid())
    [System.IO.File]::WriteAllText($probePath, "archive health check")
    Remove-Item -LiteralPath $probePath -Force
    Write-Output "PASS: archive directory exists and is writable."

    if (-not $PythonExe) {
        $PythonExe = Join-Path $InstallPath ".venv\Scripts\python.exe"
    }
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Configured virtual-environment Python executable not found: $PythonExe"
    }
    $env:WA_HEALTH_DB_PATH = Join-Path $paths.StatePath "processed_messages.sqlite3"
    $sqliteCheck = "import os,sqlite3; p=os.environ['WA_HEALTH_DB_PATH']; c=sqlite3.connect(p,timeout=5); r=c.execute('PRAGMA quick_check').fetchone(); t=c.execute(""SELECT name FROM sqlite_master WHERE type='table' AND name='processing_state'"").fetchone(); c.close(); assert r == ('ok',), r; assert t is not None, 'processing_state table is missing'; print('SQLite integrity OK')"
    & $PythonExe -c $sqliteCheck
    if ($LASTEXITCODE -ne 0) {
        throw "SQLite state is inaccessible or failed PRAGMA quick_check."
    }
    Write-Output "PASS: SQLite state is accessible and passes quick_check."
    Write-Output "PASS"
    exit 0
}
catch {
    [Console]::Error.WriteLine("FAIL: {0}", $_.Exception.Message)
    exit 1
}
