#!/bin/bash
# Deploy de desenvolvimento pra VM (usuário final: release + tools/install.ps1): empacota o hammertools,
# instala com uv, roda `ht setup` (FGD cp1252 + sequências), copia a fixture, compila a fixture (vvis completo, tudo é func_detail) e
# regenera o preview. Uso: tools/deploy.sh [--no-compile] [--reload]
set -e
cd "$(dirname "$0")/.."
COMPILE=1; RELOAD=0
for a in "$@"; do case $a in --no-compile) COMPILE=0;; --reload) RELOAD=1;; esac; done
rm -rf vm-share/hammertools_pkg vm-share/hammertools_pkg.zip
mkdir -p vm-share/hammertools_pkg && cp -r hammertools pyproject.toml vm-share/hammertools_pkg/
find vm-share/hammertools_pkg -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
(cd vm-share && python3 -c "import shutil; shutil.make_archive('hammertools_pkg','zip','.','hammertools_pkg')")
cp maps/test_stairs.vmf vm-share/
PS='$h="http://10.0.2.2:8090"; $g="C:\Program Files (x86)\Steam\steamapps\common\GarrysMod"; $w="C:\Users\Quickemu\hammer"; $m="$g\sourcesdk_content\garrysmod\mapsrc"; $bin="C:\Users\Quickemu\.local\bin"
Invoke-WebRequest "$h/hammertools_pkg.zip" -OutFile "$w\hammertools_pkg.zip" -UseBasicParsing; Remove-Item "$w\hammertools_pkg" -Recurse -Force -ErrorAction SilentlyContinue; Expand-Archive "$w\hammertools_pkg.zip" -DestinationPath $w -Force
$env:UV_TOOL_DIR="C:\Users\Quickemu\AppData\Roaming\uv\tools"; $env:UV_TOOL_BIN_DIR=$bin; $env:UV_CACHE_DIR="C:\Users\Quickemu\AppData\Local\uv\cache"
$uv = Get-ChildItem "C:\Users\Quickemu\AppData\Local\Microsoft\WinGet\Packages" -Recurse -Filter uv.exe | Select -First 1 -Expand FullName
& $uv tool install --force --python 3.12 --with numpy --with scipy "$w\hammertools_pkg" 2>&1 | Out-Null
Invoke-WebRequest "$h/test_stairs.vmf" -OutFile "$m\test_stairs.vmf" -UseBasicParsing
# FGD (cp1252), ht-lint.cmd e sequências "ht lint"/"ht final": o mesmo `ht setup` que o release usa
& "$bin\ht.exe" setup --game $g
"instalado; fgd " + (Get-Item "$g\bin\win64\hammerplusplus\hammertools.fgd").LastWriteTime.ToString("HH:mm:ss")'
if [ $COMPILE = 1 ]; then PS="$PS"'
$o = & "$bin\ht-vbsp.exe" -game "$g\garrysmod" "$m\test_stairs" 2>&1 | Out-String; ($o -split "`n" | ? { $_ -match "ht-vbsp:|leaked|unbounded|aviso" } | % { $_.Trim() })
& "$g\bin\win64\vvis.exe" -game "$g\garrysmod" "$m\test_stairs" 2>&1 | Out-Null; & "$g\bin\win64\vrad.exe" -game "$g\garrysmod" "$m\test_stairs" 2>&1 | Out-Null
Copy-Item "$m\test_stairs.bsp" "$g\garrysmod\maps\test_stairs.bsp" -Force; "maps bsp: " + [math]::Round((Get-Item "$g\garrysmod\maps\test_stairs.bsp").Length/1KB) + " KB"
& "$bin\ht-preview.cmd" "$m\test_stairs" 2>&1 | Out-Null; "preview regenerado"'; fi
if [ $RELOAD = 1 ]; then PS="$PS"'
Start-Process -FilePath "$g\bin\win64\gmod.exe" -WorkingDirectory $g -ArgumentList "-hijack","-game","`"$g\garrysmod`"","+map","test_stairs"; "gmod recarregado"'; fi
~/vms/qga.sh "$PS" 900 2>/dev/null | grep -v -E "CLIXML|^<Objs"
