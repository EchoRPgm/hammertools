# Setup da VM pro Hammer++ + Windows-MCP. Rodar em PowerShell como admin:
#   & ([scriptblock]::Create((irm http://10.0.2.2:8090/setup.ps1))) -AuthKey <chave>
param([Parameter(Mandatory)][string]$AuthKey)   # chave do Windows-MCP (a mesma do cliente MCP no host)
$ErrorActionPreference = "Continue"
$host_ = "http://10.0.2.2:8090"

Write-Host "== winget: Steam + 7zip + Python/uv" -ForegroundColor Cyan
winget install --id Valve.Steam -e --accept-source-agreements --accept-package-agreements
winget install --id 7zip.7zip -e --accept-package-agreements
winget install --id astral-sh.uv -e --accept-package-agreements
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

Write-Host "== Hammer++ zip" -ForegroundColor Cyan
New-Item -ItemType Directory -Force "$env:USERPROFILE\hammer" | Out-Null
Invoke-WebRequest "$host_/hammerplusplus_gmod_build8871.zip" -OutFile "$env:USERPROFILE\hammer\hammerplusplus.zip"

Write-Host "== Windows-MCP (streamable-http em 0.0.0.0:8000, autostart no logon)" -ForegroundColor Cyan
uvx windows-mcp install --transport streamable-http --host 0.0.0.0 --port 8000 --auth-key $AuthKey
New-NetFirewallRule -DisplayName "Windows-MCP 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow | Out-Null
uvx windows-mcp serve --transport streamable-http --host 0.0.0.0 --port 8000 --auth-key $AuthKey

Write-Host "== pronto. Instala o GMod (branch x86-64) pelo Steam e depois extrai hammerplusplus.zip em GarrysMod\bin\win64" -ForegroundColor Green
