# Instalação do hammertools no Windows (Hammer++ do GMod), a partir do último release do GitHub.
# PowerShell (sem admin): powershell -ExecutionPolicy Bypass -File install.ps1 -Token <token de leitura>
# (repo privado: fine-grained token só com "Contents: read" neste repo). Feche o Hammer++ antes.
# Depois disso o `ht` se atualiza sozinho (1x por dia) ou com `ht update`.
param([string]$Token = $env:HT_GITHUB_TOKEN, [string]$Game = "")
$ErrorActionPreference = "Stop"
$repo = "EchoRPgm/hammertools"
if (-not $Token) { throw "passe -Token <token> (ou defina HT_GITHUB_TOKEN)" }
$h = @{ Authorization = "Bearer $Token"; "User-Agent" = "hammertools-install"; "X-GitHub-Api-Version" = "2022-11-28" }

# uv (gerencia o Python 3.12 e o ambiente do ht; não precisa de Python instalado nem de admin)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";$HOME\.local\bin"
}

$rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers $h
$asset = $rel.assets | Where-Object { $_.name -like "*.whl" } | Select-Object -First 1
if (-not $asset) { throw "release $($rel.tag_name) sem wheel" }
$dir = Join-Path $env:TEMP "ht-install"; New-Item -ItemType Directory -Force $dir | Out-Null
$whl = Join-Path $dir $asset.name
# a API responde 302 pra uma URL assinada que recusa o header Authorization: pega o Location sem seguir
$req = [Net.HttpWebRequest]::Create($asset.url); $req.AllowAutoRedirect = $false
$req.Headers["Authorization"] = "Bearer $Token"; $req.Accept = "application/octet-stream"; $req.UserAgent = "hammertools-install"
$resp = $req.GetResponse(); $loc = $resp.Headers["Location"]; $resp.Close()
if ($loc) { Invoke-WebRequest $loc -OutFile $whl -UseBasicParsing } else { Invoke-WebRequest $asset.url -Headers ($h + @{ Accept = "application/octet-stream" }) -OutFile $whl -UseBasicParsing }
Write-Host "== hammertools $($rel.tag_name)" -ForegroundColor Cyan

uv tool install --force --python 3.12 --with numpy --with scipy $whl
uv tool update-shell | Out-Null
$bin = (uv tool dir --bin).Trim()
$ht = Join-Path $bin "ht.exe"

# token pro auto-update (fica só nesta conta do Windows)
$cfg = Join-Path $env:LOCALAPPDATA "hammertools"; New-Item -ItemType Directory -Force $cfg | Out-Null
Set-Content -Path (Join-Path $cfg "token") -Value $Token -NoNewline

if ($Game) { & $ht setup --game $Game } else { & $ht setup }
& $ht --version
Write-Host "pronto. Abra o Hammer++ (feche antes de rodar o install/ht setup: ao fechar ele regrava o gameconfig)." -ForegroundColor Green
Write-Host "Compile pela sequência 'ht final' (F9 > Expert). Atualização: automática (1x por dia) ou 'ht update'." -ForegroundColor Green
