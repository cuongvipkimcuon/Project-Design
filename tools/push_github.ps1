# Tao repo GitHub "Project-Design" va push (can dang nhap gh truoc).
# Chay: gh auth login
# Sau do: powershell -ExecutionPolicy Bypass -File tools/push_github.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Error "Chua cai GitHub CLI (gh). Cai bang: winget install GitHub.cli"
}

gh auth status | Out-Null

if (-not (git rev-parse --verify main 2>$null)) {
    git branch -M main
}

$remote = git remote get-url origin 2>$null
if (-not $remote) {
    gh repo create "Project-Design" `
        --public `
        --description "Project Design - DG Hub label planning" `
        --source=. `
        --remote=origin `
        --push
} else {
    git push -u origin main
}

Write-Host "Done. Repo: https://github.com/$(gh api user -q .login)/Project-Design"
