# Run `.\tools.ps1 <command>` from the repository root.
# Make and Docker are not installed on this host, so this script is the single
# entry point (recorded in QUESTIONS.md).
param(
    [Parameter(Position = 0)]
    [ValidateSet("dev", "test", "lint", "typecheck", "build", "accept", "db-up", "db-down", "db-reset", "eval-qa", "gen-api")]
    [string]$Command = "accept"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Py = Join-Path $Root "backend\.venv\Scripts\python.exe"
$Runtime = "D:\research-runtime"

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

function Start-Services {
    if (-not (Test-Path (Join-Path $Runtime "pgsql"))) { throw "portable PostgreSQL missing at $Runtime\pgsql" }
    $pgUp = & (Join-Path $Runtime "pgsql\bin\pg_isready.exe") -h 127.0.0.1 -p 55432 2>&1
    if ($LASTEXITCODE -ne 0) {
        & (Join-Path $Runtime "pgsql\bin\pg_ctl.exe") -D (Join-Path $Runtime "pgdata") -l (Join-Path $Runtime "pg.log") -o "-p 55432 -c listen_addresses=127.0.0.1" start | Out-Null
        Start-Sleep -Seconds 2
    }
    $redisUp = Test-NetConnection -ComputerName 127.0.0.1 -Port 56379 -InformationLevel Quiet -WarningAction SilentlyContinue
    if (-not $redisUp) {
        Start-Process -FilePath (Join-Path $Runtime "redis\redis-server.exe") -ArgumentList "--port", "56379", "--bind", "127.0.0.1", "--save", '""', "--appendonly", "no" -WindowStyle Hidden
        Start-Sleep -Seconds 2
    }
    Write-Host "postgres :55432 / redis :56379 ready" -ForegroundColor Green
}

switch ($Command) {
    "db-up" { Start-Services }

    "db-down" {
        & (Join-Path $Runtime "pgsql\bin\pg_ctl.exe") -D (Join-Path $Runtime "pgdata") stop -m fast
        Get-Process redis-server -ErrorAction SilentlyContinue | Stop-Process -Force
    }

    "db-reset" {
        & (Join-Path $Runtime "pgsql\bin\pg_ctl.exe") -D (Join-Path $Runtime "pgdata") stop -m fast -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        & $Py -c @"
import asyncio, sys
sys.path.insert(0, r'$Root\backend')
from app.db import get_engine
from app.models.orm import Base
async def main():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print('schema rebuilt')
asyncio.run(main())
"@
    }

    "lint" {
        Invoke-Step "ruff" { & $Py -m ruff check (Join-Path $Root "backend\app") (Join-Path $Root "backend\tests") }
        Invoke-Step "eslint" { Push-Location (Join-Path $Root "frontend"); try { & npx eslint . } finally { Pop-Location } }
    }

    "typecheck" {
        Invoke-Step "mypy" { Push-Location (Join-Path $Root "backend"); try { & $Py -m mypy app } finally { Pop-Location } }
        Invoke-Step "tsc" { Push-Location (Join-Path $Root "frontend"); try { & npx tsc -b --pretty false } finally { Pop-Location } }
    }

    "test" {
        Invoke-Step "pytest" { Push-Location (Join-Path $Root "backend"); try { & $Py -m pytest tests -q } finally { Pop-Location } }
        Invoke-Step "vitest" { Push-Location (Join-Path $Root "frontend"); try { & npx vitest run } finally { Pop-Location } }
    }

    "build" {
        # vite prints chunk-size notices on stderr; under
        # $ErrorActionPreference=Stop, PowerShell 5.1 turns a native command's
        # stderr into a terminating error even when the exit code is 0. The
        # exit code, not the stream, decides this step.
        Invoke-Step "vite build" {
            Push-Location (Join-Path $Root "frontend")
            $previous = $ErrorActionPreference
            try {
                $ErrorActionPreference = "Continue"
                & npx vite build
            } finally {
                $ErrorActionPreference = $previous
                Pop-Location
            }
        }
    }

    "accept" {
        # Each step runs as a child script; `exit` there only sets
        # $LASTEXITCODE, so check it before continuing.
        foreach ($step in "lint", "typecheck", "test", "build") {
            & $PSCommandPath $step
            if ($LASTEXITCODE -ne 0) {
                Write-Host "`nACCEPTANCE FAILED at $step" -ForegroundColor Red
                exit $LASTEXITCODE
            }
        }
        Write-Host "`nALL GREEN" -ForegroundColor Green
    }

    "dev" {
        Start-Services
        Start-Process -FilePath $Py -ArgumentList "run_server.py" -WorkingDirectory (Join-Path $Root "backend")
        Start-Process -FilePath $Py -ArgumentList "-m", "app.worker" -WorkingDirectory (Join-Path $Root "backend")
        Push-Location (Join-Path $Root "frontend")
        try { & npx vite } finally { Pop-Location }
    }

    "gen-api" {
        Push-Location (Join-Path $Root "frontend")
        try {
            & npx openapi-typescript ../openapi.yaml -o src/api/schema.d.ts
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            & git -C $Root diff --exit-code --quiet -- frontend/src/api/schema.d.ts
            if ($LASTEXITCODE -ne 0) {
                Write-Host "schema.d.ts differs from openapi.yaml — regenerate and commit" -ForegroundColor Red
                exit 1
            }
            Write-Host "generated client matches the contract" -ForegroundColor Green
        } finally { Pop-Location }
    }

    "eval-qa" { Invoke-Step "eval" { Push-Location (Join-Path $Root "backend"); try { & $Py -m app.eval_qa } finally { Pop-Location } } }
}
