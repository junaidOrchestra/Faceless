# Apply SQL migrations to local docker-compose Postgres.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
Get-Content clip-server/migrations.sql -Raw | docker compose exec -T db psql -U faceless -d clip
Get-Content orchestrator/migrations.sql -Raw | docker compose exec -T db psql -U faceless -d orchestrator
Write-Host "Migrations applied to clip and orchestrator databases."
Pop-Location
