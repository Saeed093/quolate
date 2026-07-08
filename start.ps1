<#
.SYNOPSIS
  Start the full Quolate dev stack on Windows.

.DESCRIPTION
  Brings up Postgres (pgvector via Docker), ensures Ollama is reachable,
  runs Alembic migrations, then launches the backend and frontend in
  separate PowerShell windows.

  Prerequisites: Docker Desktop, Python 3.10+ venv in backend/.venv,
  Node 20+, Ollama. See README.md for first-time setup.

.EXAMPLE
  .\start.ps1

.EXAMPLE
  .\start.ps1 -SkipMigrate
#>
[CmdletBinding()]
param(
    [switch]$SkipMigrate,
    [switch]$SkipOllamaCheck
)

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$composeFile = Join-Path $root "docker-compose.yml"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
$dbContainer = "quolate_db"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-CommandAvailable([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-EnvFiles {
    $envFile = Join-Path $root ".env"
    $envExample = Join-Path $root ".env.example"
    if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
        Copy-Item $envExample $envFile
        Write-Host "Created .env from .env.example"
    }

    $feEnv = Join-Path $frontend ".env.local"
    $feExample = Join-Path $frontend ".env.local.example"
    if (-not (Test-Path $feEnv) -and (Test-Path $feExample)) {
        Copy-Item $feExample $feEnv
        Write-Host "Created frontend/.env.local from .env.local.example"
    }
}

function Test-Prerequisites {
    Write-Step "Checking prerequisites"

    if (-not (Test-Path $venvPython)) {
        throw @"
Backend virtualenv not found at:
  $venvPython

First-time setup:
  cd backend
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
"@
    }

    if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
        throw @"
Frontend dependencies not installed.

First-time setup:
  cd frontend
  npm install
"@
    }

    if (-not (Test-CommandAvailable "docker")) {
        throw "Docker is not on PATH. Install Docker Desktop and try again."
    }

    if (-not $SkipOllamaCheck -and -not (Test-CommandAvailable "ollama")) {
        throw "Ollama is not on PATH. Install Ollama for Windows and try again."
    }

    Write-Host "Prerequisites OK"
}

function Test-DockerReady {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        docker info *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $prev
    }
}

function Wait-DockerDaemon {
    param([int]$TimeoutSeconds = 120)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerReady) {
            return
        }
        Start-Sleep -Seconds 3
    }

    throw "Docker daemon did not become ready within ${TimeoutSeconds}s. Is Docker Desktop running?"
}

function Ensure-DockerRunning {
    Write-Step "Starting Docker"

    if (Test-DockerReady) {
        Write-Host "Docker is already running"
        return
    }

    $dockerDesktop = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $dockerDesktop)) {
        throw "Docker is not running and Docker Desktop was not found at:`n  $dockerDesktop"
    }

    Write-Host "Launching Docker Desktop..."
    Start-Process $dockerDesktop | Out-Null
    Wait-DockerDaemon
    Write-Host "Docker is ready"
}

function Start-Database {
    Write-Step "Starting Postgres (pgvector)"

    docker compose -f $composeFile up -d db
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed"
    }

    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        try {
            $status = docker inspect --format "{{.State.Health.Status}}" $dbContainer 2>$null
        }
        finally {
            $ErrorActionPreference = $prev
        }
        if ($status -eq "healthy") {
            Write-Host "Database is healthy (localhost:5433)"
            return
        }
        Start-Sleep -Seconds 2
    }

    throw "Database container '$dbContainer' did not become healthy in time. Check: docker logs $dbContainer"
}

function Invoke-Migrate {
    Write-Step "Applying database migrations"

    Push-Location $backend
    try {
        & $venvPython -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "alembic upgrade head failed"
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "Migrations applied"
}

function Test-OllamaReachable {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Ensure-Ollama {
    Write-Step "Checking Ollama"

    if (Test-OllamaReachable) {
        Write-Host "Ollama is reachable (localhost:11434)"
        return
    }

    Write-Host "Ollama not responding - waking with 'ollama list'..."
    ollama list *> $null

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        if (Test-OllamaReachable) {
            Write-Host "Ollama is reachable (localhost:11434)"
            return
        }
        Start-Sleep -Seconds 2
    }

    Write-Warning @"
Ollama is still not reachable. LLM features will be unavailable.
Start Ollama manually, then verify with: ollama list
"@
}

function Start-ServiceWindow {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$Command
    )

    $launch = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location '$WorkingDirectory'; $Command"
    Start-Process powershell -ArgumentList "-NoExit", "-NoLogo", "-Command", $launch | Out-Null
}

function Start-Backend {
    Write-Step "Starting backend"

    Start-ServiceWindow `
        -Title "Quolate Backend (:8000)" `
        -WorkingDirectory $backend `
        -Command ".\.venv\Scripts\python.exe run.py"

    Write-Host "Backend window opened - http://localhost:8000"
}

function Start-Frontend {
    Write-Step "Starting frontend"

    Start-ServiceWindow `
        -Title "Quolate Frontend (:3000)" `
        -WorkingDirectory $frontend `
        -Command "npm run dev"

    Write-Host "Frontend window opened - http://localhost:3000"
}

function Open-AppInBrowser {
    param(
        [string]$Url = "http://localhost:3000",
        [int]$TimeoutSeconds = 60
    )

    Write-Step "Opening browser"

    $ready = $false
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200) {
                $ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $ready) {
        Write-Host "Frontend is still starting - opening browser anyway"
    }

    Start-Process $Url | Out-Null
    Write-Host "Opened $Url in your default browser"
}

function Show-Summary {
    Write-Host ""
    Write-Host "Quolate is starting." -ForegroundColor Green
    Write-Host ""
    Write-Host "  App:      http://localhost:3000"
    Write-Host "  API:      http://localhost:8000"
    Write-Host "  API docs: http://localhost:8000/docs"
    Write-Host "  Health:   http://localhost:8000/health"
    Write-Host "  Database: localhost:5433 (user/pass/db: quolate)"
    Write-Host "  Ollama:   http://localhost:11434"
    Write-Host ""
    Write-Host "Backend and frontend run in separate windows. Close those windows (or Ctrl+C) to stop them."
    Write-Host "Stop the database with: docker compose -f docker-compose.yml down"
}

# --- main ---
Write-Host "Quolate dev stack" -ForegroundColor Green

Ensure-EnvFiles
Test-Prerequisites
Ensure-DockerRunning
Start-Database

if (-not $SkipMigrate) {
    Invoke-Migrate
}

if (-not $SkipOllamaCheck) {
    Ensure-Ollama
}

Start-Backend
Start-Sleep -Seconds 2
Start-Frontend
Open-AppInBrowser
Show-Summary
