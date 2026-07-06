<#
Quolate task runner for Windows PowerShell.

Usage:
  .\tasks.ps1 dev       # run backend (uvicorn) with reload
  .\tasks.ps1 web       # run frontend (next dev)
  .\tasks.ps1 db        # start Postgres via docker compose
  .\tasks.ps1 migrate   # alembic upgrade head
  .\tasks.ps1 revision  # alembic autogenerate revision -m "<msg>"
  .\tasks.ps1 test      # backend pytest (mock LLM)
  .\tasks.ps1 seed      # seed demo user + project
  .\tasks.ps1 seed-duty # seed illustrative Pakistan duty/tax rates (demo)
#>
param(
    [Parameter(Position = 0)]
    [string]$Task = "help",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

function Invoke-Backend([string[]]$cmd) {
    Push-Location $backend
    try { & $cmd[0] $cmd[1..($cmd.Length - 1)] }
    finally { Pop-Location }
}

switch ($Task) {
    "db" {
        docker compose -f (Join-Path $root "docker-compose.yml") up -d db
    }
    "dev" {
        # run.py forces the selector event loop on Windows (psycopg async needs it).
        Invoke-Backend @("python", "run.py")
    }
    "web" {
        Push-Location $frontend
        try { npm run dev }
        finally { Pop-Location }
    }
    "migrate" {
        Invoke-Backend @("python", "-m", "alembic", "upgrade", "head")
    }
    "revision" {
        $msg = if ($Rest) { $Rest -join " " } else { "revision" }
        Invoke-Backend @("python", "-m", "alembic", "revision", "--autogenerate", "-m", $msg)
    }
    "test" {
        $env:LLM_BASE_URL = "mock"
        Invoke-Backend @("python", "-m", "pytest", "-q")
    }
    "seed" {
        Invoke-Backend @("python", "-m", "app.scripts.seed")
    }
    "seed-duty" {
        Invoke-Backend @("python", "-m", "app.scripts.seed_duty_rates")
    }
    default {
        Get-Content (Join-Path $root "tasks.ps1") | Select-Object -First 16
    }
}
