# One-command local install on Windows (FR-SETUP-09, ADR-0071). Same behaviour as install.sh: writes .env with
# fresh secrets, starts the stack on 127.0.0.1 and waits until it is healthy.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1                      from a clone of the repository
#   $env:REPO_URL = '<git url>'; powershell -ExecutionPolicy Bypass -File install.ps1   clones first (INSTALL_DIR, default .\intake)
#
# Optional environment: WEB_PORT (8080), APP_PORT (8001), MEETING_GATEWAY_PORT (8002), COMPOSE_PROJECT_NAME.
# Secrets are written to .env only and never printed.
$ErrorActionPreference = 'Stop'

function Fail($message) { Write-Host "Error: $message" -ForegroundColor Red; exit 1 }

# Windows PowerShell 5.1 turns any native stderr line (docker prints warnings and build progress there) into a
# terminating error under 'Stop'. Run native commands with errors relaxed and judge them by $LASTEXITCODE only.
function Invoke-Native([scriptblock]$command) {
  $previous = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { & $command } finally { $ErrorActionPreference = $previous }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail 'docker is not installed. Install Docker Desktop first.' }
Invoke-Native { docker compose version *> $null }
if ($LASTEXITCODE -ne 0) { Fail "'docker compose' is not available. Update Docker Desktop." }
Invoke-Native { docker info *> $null }
if ($LASTEXITCODE -ne 0) { Fail 'the Docker daemon is not running. Start Docker Desktop and run this again.' }

$here = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
if ((Test-Path (Join-Path $here 'docker-compose.yml')) -and (Test-Path (Join-Path $here '.env.example'))) {
  Set-Location $here
} elseif ($env:REPO_URL) {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "git is required to clone $($env:REPO_URL)." }
  $target = if ($env:INSTALL_DIR) { $env:INSTALL_DIR } else { 'intake' }
  if (Test-Path $target) { Fail "$target already exists. Remove it or set INSTALL_DIR." }
  Invoke-Native { git clone --depth 1 $env:REPO_URL $target }
  if ($LASTEXITCODE -ne 0) { Fail 'git clone failed.' }
  Set-Location $target
} else {
  Fail 'run this from the repository folder, or set REPO_URL to clone it.'
}

if (Test-Path '.env') { Fail '.env already exists, so this looks like an installed copy. Delete .env only if you want a new install (it holds your secrets; back it up first).' }

function New-Secret([int]$bytes) {
  $buffer = New-Object byte[] $bytes
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($buffer)
  $rng.Dispose()
  return ([System.BitConverter]::ToString($buffer) -replace '-', '').ToLower()
}

$utf8 = New-Object System.Text.UTF8Encoding($false)
$lines = New-Object System.Collections.Generic.List[string]
foreach ($line in [System.IO.File]::ReadAllLines((Join-Path (Get-Location) '.env.example'))) { $lines.Add($line) }

# Replace KEY=... or append it when the file has no such line.
function Set-EnvValue([string]$key, [string]$value) {
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].StartsWith("$key=")) { $lines[$i] = "$key=$value"; return }
  }
  $lines.Add("$key=$value")
}

$webPort = if ($env:WEB_PORT) { $env:WEB_PORT } else { '8080' }
$appPort = if ($env:APP_PORT) { $env:APP_PORT } else { '8001' }
$pg = New-Secret 24
$redis = New-Secret 24

Set-EnvValue 'SECRET_KEY' (New-Secret 32)
Set-EnvValue 'POSTGRES_PASSWORD' $pg
Set-EnvValue 'REDIS_PASSWORD' $redis
Set-EnvValue 'DATABASE_URL' "postgresql+psycopg://intake:${pg}@postgres:5432/intake"
Set-EnvValue 'REDIS_URL' "redis://:${redis}@redis:6379/0"
Set-EnvValue 'CELERY_BROKER_URL' "redis://:${redis}@redis:6379/1"
Set-EnvValue 'SEAWEEDFS_S3_ACCESS_KEY' ('intake' + (New-Secret 8))
Set-EnvValue 'SEAWEEDFS_S3_SECRET_KEY' (New-Secret 24)
Set-EnvValue 'BACKUP_PASSPHRASE' (New-Secret 16)
Set-EnvValue 'CTO_INITIAL_PASSWORD' (New-Secret 16)
Set-EnvValue 'PROJECT_OWNER_INITIAL_PASSWORD' ''
Set-EnvValue 'FIRST_RUN_WIZARD' 'true'
Set-EnvValue 'WEB_BIND_ADDRESS' '127.0.0.1'
Set-EnvValue 'APP_BIND_ADDRESS' '127.0.0.1'
Set-EnvValue 'WEB_PORT' $webPort
Set-EnvValue 'APP_PORT' $appPort
Set-EnvValue 'APP_PUBLIC_URL' "http://127.0.0.1:$webPort"
if ($env:COMPOSE_PROJECT_NAME) { Set-EnvValue 'COMPOSE_PROJECT_NAME' $env:COMPOSE_PROJECT_NAME }
if ($env:MEETING_GATEWAY_PORT) { Set-EnvValue 'MEETING_GATEWAY_PORT' $env:MEETING_GATEWAY_PORT }
# LF endings, no BOM: compose and the containers read this file.
[System.IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), (($lines -join "`n") + "`n"), $utf8)
Write-Host 'Wrote .env with new secrets (not shown).'

Write-Host 'Building and starting the stack. The first run takes a few minutes.'
Invoke-Native { docker compose up -d --build }
if ($LASTEXITCODE -ne 0) { Fail 'docker compose up failed.' }

Write-Host 'Waiting for the app to be ready...'
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$webPort/api/v1/health/ready" -TimeoutSec 5
    if ($response.StatusCode -eq 200) { $ready = $true; break }
  } catch { }
  Start-Sleep -Seconds 2
}
if (-not $ready) { Fail 'the app did not become ready in 4 minutes. Check: docker compose ps  and  docker compose logs api' }
try { Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$webPort/web-health" -TimeoutSec 5 | Out-Null } catch { Fail 'the web container is not answering. Check: docker compose logs web' }

Write-Host ''
Write-Host 'Intake is running. Open this address in your browser and create the first accounts:'
Write-Host ''
Write-Host "    http://127.0.0.1:$webPort/"
Write-Host ''
Write-Host 'Before you continue:'
Write-Host '  - Back up the .env file in this folder somewhere safe. Changing or losing SECRET_KEY makes saved AI keys unreadable.'
Write-Host '  - Until you create the accounts, the first visitor becomes the CTO. This install only listens on 127.0.0.1;'
Write-Host '    do not expose the port to a network before you have finished the setup page.'
Write-Host '  - You will need an API key for an OpenAI-compatible AI provider on the setup page.'
