Set-StrictMode -Version Latest

function Assert-AbsoluteWindowsPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,
        [Parameter(Mandatory = $true)]
        [string] $Name
    )

    if ($Path -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+(?:\\|$))') {
        throw "$Name must be a fully qualified Windows drive or UNC path."
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($fullPath)
    if ($fullPath.TrimEnd("\").Equals($root.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Name must not be a drive or share root."
    }
}

function Import-ArchiveEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Configuration file not found: $Path"
    }

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }

        $separator = $trimmed.IndexOf("=")
        if ($separator -lt 1) {
            throw "Invalid configuration line in $Path."
        }

        $name = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim()
        if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw "Invalid environment variable name in $Path."
        }
        if ($value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        $values[$name] = $value
        Set-Item -Path "Env:$name" -Value $value
    }

    return $values
}

function Get-ArchivePathConfiguration {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable] $Environment,
        [Parameter(Mandatory = $true)]
        [string] $DataPath
    )

    $archivePath = [string]$Environment["ARCHIVE_PATH"]
    if ([string]::IsNullOrWhiteSpace($archivePath)) {
        throw "ARCHIVE_PATH must be configured."
    }
    Assert-AbsoluteWindowsPath -Path $archivePath -Name "ARCHIVE_PATH"

    $statePath = [string]$Environment["STATE_DB_PATH"]
    if ([string]::IsNullOrWhiteSpace($statePath)) {
        $statePath = Join-Path $DataPath "state"
    }
    }
    Assert-AbsoluteWindowsPath -Path $statePath -Name "STATE_DB_PATH"

    $portText = [string]$Environment["WEBHOOK_PORT"]
    if ([string]::IsNullOrWhiteSpace($portText)) {
        $portText = "8000"
    }
    $port = 0
    if (-not [int]::TryParse($portText, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw "WEBHOOK_PORT must be an integer between 1 and 65535."
    }

    $hostName = [string]$Environment["WEBHOOK_HOST"]
    if ([string]::IsNullOrWhiteSpace($hostName)) {
        $hostName = "127.0.0.1"
    }
    if ($hostName -ne "127.0.0.1") {
        throw "WEBHOOK_HOST must be 127.0.0.1 in this deployment phase."
    }

    $verifyToken = [string]$Environment["WHATSAPP_VERIFY_TOKEN"]
    if ([string]::IsNullOrWhiteSpace($verifyToken) -or $verifyToken -eq "replace-with-whatsapp-verify-token" -or $verifyToken -eq "replace-me") {
        throw "Set WHATSAPP_VERIFY_TOKEN to a non-placeholder value in the deployment .env file."
    }

    return @{
        ArchivePath = [System.IO.Path]::GetFullPath($archivePath)
        StatePath = [System.IO.Path]::GetFullPath($statePath)
        WebhookPort = $port
        WebhookHost = $hostName
    }
}

function Assert-DisjointDeploymentPaths {
    param(
        [Parameter(Mandatory = $true)]
        [string] $ArchivePath,
        [Parameter(Mandatory = $true)]
        [string] $StatePath,
        [Parameter(Mandatory = $true)]
        [string] $InstallPath,
        [Parameter(Mandatory = $true)]
        [string] $DataPath
    )

    $paths = @{
        Archive = [System.IO.Path]::GetFullPath($ArchivePath).TrimEnd("\")
        State = [System.IO.Path]::GetFullPath($StatePath).TrimEnd("\")
        Install = [System.IO.Path]::GetFullPath($InstallPath).TrimEnd("\")
        Data = [System.IO.Path]::GetFullPath($DataPath).TrimEnd("\")
    }
    Assert-AbsoluteWindowsPath -Path $InstallPath -Name "InstallPath"
    Assert-AbsoluteWindowsPath -Path $DataPath -Name "DataPath"
    foreach ($left in @("Archive", "State", "Install", "Data")) {
        foreach ($right in @("Archive", "State", "Install", "Data")) {
            if ($left -ge $right) {
                continue
            }
            if (($left -eq "State" -and $right -in @("Archive", "Data")) -or
                ($right -eq "State" -and $left -in @("Archive", "Data"))) {
                continue
            }
            $a = $paths[$left]
            $b = $paths[$right]
            $separator = [System.IO.Path]::DirectorySeparatorChar
            if ($a.Equals($b, [StringComparison]::OrdinalIgnoreCase) -or
                $a.StartsWith($b + $separator, [StringComparison]::OrdinalIgnoreCase) -or
                $b.StartsWith($a + $separator, [StringComparison]::OrdinalIgnoreCase)) {
                throw "$left and $right paths must not overlap; refusing an unsafe deployment layout."
            }
        }
    }
}

function Set-ReadOnlyDirectoryAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    & icacls.exe $Path /grant "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)RX" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant the Windows service account read/execute access to $Path (icacls exit code $LASTEXITCODE)."
    }
}

function Set-DirectoryAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    & icacls.exe $Path /grant "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)M" /C | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant the Windows service account access to $Path (icacls exit code $LASTEXITCODE)."
    }
}
