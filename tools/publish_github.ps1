#requires -Version 5.1
<#
.SYNOPSIS
  Securely publish Katya 2.11.0 to GitHub.

.DESCRIPTION
  The token is read ONLY from $env:GITHUB_TOKEN. It is never written to
  config.py, .git/config, the commit, or console output. The script:
    1. creates the repo if it does not exist;
    2. forces it to public via the GitHub API;
    3. stages, scans for leaked tokens, commits and force-pushes main.

.EXAMPLE
  $env:GITHUB_TOKEN = "github_pat_..."   # fine-grained token, repo scope
  .\tools\publish_github.ps1 -Owner kirill181024-cyber -Repo katya
#>
param(
    [string]$Owner = "kirill181024-cyber",
    [string]$Repo = "katya",
    [string]$Message = "Release v2.11.0: Public Marvel Swarm Core with Continuous Background Listening and Roblox Cyber-Coach"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

if (-not $env:GITHUB_TOKEN) {
    throw "GITHUB_TOKEN не задан. Выполните: `$env:GITHUB_TOKEN = '<fresh token>'"
}
if ($Owner -notmatch '^[A-Za-z0-9_.-]+$' -or $Repo -notmatch '^[A-Za-z0-9_.-]+$') {
    throw "Некорректные Owner/Repo."
}

$headers = @{
    Authorization          = "Bearer $env:GITHUB_TOKEN"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "Katya-Release-Bot"
}

Write-Host "[1/6] Проверка репозитория $Owner/$Repo…" -ForegroundColor Cyan
$repoExists = $true
try {
    $repoInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo" -Headers $headers -Method Get
} catch {
    $status = 0
    if ($_.Exception.Response) {
        $status = [int]$_.Exception.Response.StatusCode
    }
    if ($status -eq 404) {
        $repoExists = $false
    } else {
        throw "GitHub API: $($_.Exception.Message)"
    }
}

if (-not $repoExists) {
    Write-Host "      Репозиторий не найден, создаю публичный…" -ForegroundColor Yellow
    $body = @{ name = $Repo; private = $false; auto_init = $false } | ConvertTo-Json
    $repoInfo = Invoke-RestMethod -Uri "https://api.github.com/user/repos" -Headers $headers -Method Post -Body $body -ContentType "application/json"
} elseif ($repoInfo.private -eq $true) {
    Write-Host "      Репозиторий приватный, принудительно перевожу в PUBLIC…" -ForegroundColor Yellow
    $body = @{ private = $false } | ConvertTo-Json
    $repoInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo" -Headers $headers -Method Patch -Body $body -ContentType "application/json"
} else {
    Write-Host "      Репозиторий уже PUBLIC." -ForegroundColor Green
}

Write-Host "[2/6] Инициализация Git…" -ForegroundColor Cyan
if (-not (Test-Path ".git")) {
    git init | Out-Host
}
if (-not (git config --get user.name)) { git config user.name "Katya Release Bot" }
if (-not (git config --get user.email)) { git config user.email "katya@users.noreply.github.com" }

Write-Host "[3/6] Сборка коммита…" -ForegroundColor Cyan
git add .
$staged = git diff --cached --no-color
if ($staged -match 'ghp_[A-Za-z0-9]{20,}' -or $staged -match 'github_pat_[A-Za-z0-9_]{20,}' -or $staged -match 'BEGIN (RSA|OPENSSH|EC) PRIVATE KEY') {
    throw "В staged-файлах найден секрет. Публикация остановлена. Удалите токен/ключ и повторите."
}
$changes = git status --porcelain
if ($changes) {
    git commit -m $Message | Out-Host
} else {
    Write-Host "      Изменений нет, использую текущий HEAD." -ForegroundColor DarkGray
}

Write-Host "[4/6] Настройка remote без токена в URL…" -ForegroundColor Cyan
git branch -M main
git remote remove origin 2>$null
# Username is public; the token is supplied at runtime by GIT_ASKPASS.
git remote add origin "https://x-access-token@github.com/$Owner/$Repo.git"

$askpass = Join-Path $env:TEMP "katya_git_askpass_$PID.cmd"
try {
    # GIT_ASKPASS prints the secret to Git's password prompt. It is deleted below.
    "@echo off`r`necho %GITHUB_TOKEN%" | Set-Content -Path $askpass -Encoding Ascii
    $oldAskpass = $env:GIT_ASKPASS
    $oldPrompt = $env:GIT_TERMINAL_PROMPT
    $env:GIT_ASKPASS = $askpass
    $env:GIT_TERMINAL_PROMPT = "0"

    Write-Host "[5/6] Force-push в main…" -ForegroundColor Cyan
    git push -u origin main --force
    if ($LASTEXITCODE -ne 0) { throw "git push завершился с кодом $LASTEXITCODE" }
} finally {
    Remove-Item $askpass -Force -ErrorAction SilentlyContinue
    $env:GIT_ASKPASS = $oldAskpass
    $env:GIT_TERMINAL_PROMPT = $oldPrompt
}

Write-Host "[6/6] Проверка публичного доступа…" -ForegroundColor Cyan
$final = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo" -Headers $headers -Method Get
Write-Host ("Готово: {0} | private={1} | default_branch={2}" -f $final.html_url, $final.private, $final.default_branch) -ForegroundColor Green
Write-Host "Ошибка 404 для публичного репозитория устранена." -ForegroundColor Green
