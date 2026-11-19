param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('api', 'ui', 'db', 'all')]
  [string]$Mode
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$EnvFile = Join-Path $ProjectRoot '.env'
$ReportDir = Join-Path $ProjectRoot 'reports'
$ReportFile = Join-Path $ReportDir 'minimall_test_report.html'

function Get-DotEnvMap {
  $Map = @{}

  if (-not (Test-Path -LiteralPath $EnvFile)) {
    return $Map
  }

  $Lines = Get-Content -LiteralPath $EnvFile
  foreach ($LineItem in $Lines) {
    $Line = $LineItem.Trim()

    if ($Line.Length -eq 0) {
      continue
    }

    if ($Line.StartsWith('#')) {
      continue
    }

    $EqualIndex = $Line.IndexOf('=')
    if ($EqualIndex -lt 1) {
      continue
    }

    $Key = $Line.Substring(0, $EqualIndex).Trim()
    $Value = $Line.Substring($EqualIndex + 1).Trim()

    if ($Value.Length -ge 2) {
      $FirstChar = $Value.Substring(0, 1)
      $LastChar = $Value.Substring($Value.Length - 1, 1)
      if (($FirstChar -eq '"' -and $LastChar -eq '"') -or ($FirstChar -eq "'" -and $LastChar -eq "'")) {
        $Value = $Value.Substring(1, $Value.Length - 2)
      }
    }

    $Map[$Key] = $Value
  }

  return $Map
}

function Get-ConfigValue {
  param(
    [string]$Key,
    [string]$DefaultValue,
    [hashtable]$DotEnvMap
  )

  $EnvValue = [Environment]::GetEnvironmentVariable($Key)
  if ($null -ne $EnvValue) {
    return $EnvValue
  }

  if ($DotEnvMap.ContainsKey($Key)) {
    return $DotEnvMap[$Key]
  }

  return $DefaultValue
}

function Test-ConfigKeyExists {
  param(
    [string]$Key,
    [hashtable]$DotEnvMap
  )

  $EnvValue = [Environment]::GetEnvironmentVariable($Key)
  if ($null -ne $EnvValue) {
    return $true
  }

  return $DotEnvMap.ContainsKey($Key)
}

function Assert-MiniMallRunning {
  param([string]$BaseUrl)

  try {
    Invoke-WebRequest -Uri $BaseUrl -UseBasicParsing -TimeoutSec 3 | Out-Null
  } catch {
    Write-Host ('MiniMall is not reachable: ' + $BaseUrl) -ForegroundColor Yellow
    Write-Host 'Start MiniMall first, for example: .\scripts\start.ps1' -ForegroundColor Yellow
    exit 1
  }
}

function Assert-DbConfigReady {
  param([hashtable]$DotEnvMap)

  $RequiredKeys = @('DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD')
  $MissingKeys = @()

  foreach ($Key in $RequiredKeys) {
    if (-not (Test-ConfigKeyExists -Key $Key -DotEnvMap $DotEnvMap)) {
      $MissingKeys += $Key
    }
  }

  if ($MissingKeys.Count -gt 0) {
    Write-Host ('Missing required DB environment variables: ' + ($MissingKeys -join ', ')) -ForegroundColor Yellow
    Write-Host 'Copy .env.example to .env and fill local DB settings. This script will not guess DB password.' -ForegroundColor Yellow
    exit 1
  }
}

$DotEnvMap = Get-DotEnvMap
$BaseUrl = Get-ConfigValue -Key 'MINIMALL_BASE_URL' -DefaultValue 'http://localhost:3000' -DotEnvMap $DotEnvMap

Set-Location -LiteralPath $ProjectRoot
Assert-MiniMallRunning -BaseUrl $BaseUrl

if ($Mode -eq 'db' -or $Mode -eq 'all') {
  Assert-DbConfigReady -DotEnvMap $DotEnvMap
}

switch ($Mode) {
  'api' {
    python -m pytest python_api_tests -m 'api and not db' -v
    exit $LASTEXITCODE
  }

  'ui' {
    python -m pytest ui_tests -m 'ui' -v
    exit $LASTEXITCODE
  }

  'db' {
    python -m pytest python_api_tests -m 'db' -v
    exit $LASTEXITCODE
  }

  'all' {
    New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
    python -m pytest python_api_tests ui_tests -v --html="$ReportFile" --self-contained-html
    $ExitCode = $LASTEXITCODE

    if (Test-Path -LiteralPath $ReportFile) {
      Write-Host ('HTML report generated: ' + $ReportFile) -ForegroundColor Green
    }

    exit $ExitCode
  }
}
