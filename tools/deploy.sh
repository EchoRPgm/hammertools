#!/bin/bash
# Deploy pra VM: empacota hammertools (FGD convertido pra cp1252, que é o que o Hammer++ lê),
# instala com uv, copia FGD e fixture, compila a fixture (vvis completo, tudo é func_detail) e
# regenera o preview. Uso: tools/deploy.sh [--no-compile] [--reload]
set -e
cd "$(dirname "$0")/.."
COMPILE=1; RELOAD=0
for a in "$@"; do case $a in --no-compile) COMPILE=0;; --reload) RELOAD=1;; esac; done
rm -rf vm-share/hammertools_pkg vm-share/hammertools_pkg.zip
mkdir -p vm-share/hammertools_pkg && cp -r hammertools pyproject.toml vm-share/hammertools_pkg/
find vm-share/hammertools_pkg -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
.venv/bin/python - <<'PY'
from pathlib import Path
p = Path("vm-share/hammertools_pkg/hammertools/hammertools.fgd")
p.write_bytes(p.read_text(encoding="utf-8").encode("cp1252"))
print("FGD convertido pra cp1252")
PY
(cd vm-share && python3 -c "import shutil; shutil.make_archive('hammertools_pkg','zip','.','hammertools_pkg')")
cp maps/test_stairs.vmf vm-share/
PS='$h="http://10.0.2.2:8090"; $g="C:\Program Files (x86)\Steam\steamapps\common\GarrysMod"; $w="C:\Users\Quickemu\hammer"; $m="$g\sourcesdk_content\garrysmod\mapsrc"; $bin="C:\Users\Quickemu\.local\bin"
Invoke-WebRequest "$h/hammertools_pkg.zip" -OutFile "$w\hammertools_pkg.zip" -UseBasicParsing; Remove-Item "$w\hammertools_pkg" -Recurse -Force -ErrorAction SilentlyContinue; Expand-Archive "$w\hammertools_pkg.zip" -DestinationPath $w -Force
$env:UV_TOOL_DIR="C:\Users\Quickemu\AppData\Roaming\uv\tools"; $env:UV_TOOL_BIN_DIR=$bin; $env:UV_CACHE_DIR="C:\Users\Quickemu\AppData\Local\uv\cache"
$uv = Get-ChildItem "C:\Users\Quickemu\AppData\Local\Microsoft\WinGet\Packages" -Recurse -Filter uv.exe | Select -First 1 -Expand FullName
& $uv tool install --force --python 3.12 --with numpy --with scipy "$w\hammertools_pkg" 2>&1 | Out-Null
Copy-Item "$w\hammertools_pkg\hammertools\hammertools.fgd" "$g\bin\win64\hammerplusplus\hammertools.fgd" -Force
Invoke-WebRequest "$h/test_stairs.vmf" -OutFile "$m\test_stairs.vmf" -UseBasicParsing
# sequência "ht lint" no Hammer++ (grava <mapa>.lin se houver leak: Map > Load Pointfile)
$cmd = "@echo off`r`nsetlocal`r`nset `"in=%*`"`r`nset `"in=%in:`"=%`"`r`n:trim`r`nif `"%in:~-1%`"==`" `" (set `"in=%in:~0,-1%`" & goto trim)`r`n`"%~dp0ht.exe`" lint `"%in%.vmf`" --pointfile --game `"$g\garrysmod`"`r`n"
[IO.File]::WriteAllText("$bin\ht-lint.cmd", $cmd, [Text.Encoding]::ASCII)
$f="$g\bin\win64\hammerplusplus\hammerplusplus_sequences.cfg"; $c = Get-Content $f -Raw
if ($c -notmatch "`"ht lint`"") {
$seq = "`t`"ht lint`"`r`n`t{`r`n`t`t`"1`"`r`n`t`t{`r`n`t`t`t`"enable`"`t`t`"1`"`r`n`t`t`t`"specialcmd`"`t`t`"0`"`r`n`t`t`t`"run`"`t`t`"$bin\ht-lint.cmd`"`r`n`t`t`t`"parms`"`t`t`"`$path\`$file`"`r`n`t`t}`r`n`t}`r`n"
$c = $c -replace "^(`"Command Sequences`"\s*\r?\n\{\r?\n)", ("`$1" + ($seq -replace "\`$", "`$`$`$`$"))
Set-Content $f $c -NoNewline }
# sequência "ht final": ht-vbsp (t-junctions e faces fantasma automáticos) + vvis completo + vrad final com luz por vértice nos props (como o gm_fork) + cópia pro maps
$c = Get-Content $f -Raw
if ($c -notmatch "`"ht final`"") {
function St($i, $sc, $run, $parms) { $r = if ($run) { "`t`t`t`"run`"`t`t`"$run`"`r`n" } else { "" }; "`t`t`"$i`"`r`n`t`t{`r`n`t`t`t`"enable`"`t`t`"1`"`r`n`t`t`t`"specialcmd`"`t`t`"$sc`"`r`n$r`t`t`t`"parms`"`t`t`"$parms`"`r`n`t`t}`r`n" }
$seq = "`t`"ht final`"`r`n`t{`r`n" + (St 0 0 "`$bsp_exe" "-game `$gamedir `$path\`$file") + (St 1 0 "`$vis_exe" "-game `$gamedir `$path\`$file") + (St 2 0 "`$light_exe" "-final -StaticPropLighting -StaticPropPolys -TextureShadows -game `$gamedir `$path\`$file") + (St 3 257 "" "`$path\`$file.bsp `$bspdir\`$file.bsp") + "`t}`r`n"
$c = $c -replace "^(`"Command Sequences`"\s*\r?\n\{\r?\n)", ("`$1" + ($seq -replace "\`$", "`$`$`$`$"))
Set-Content $f $c -NoNewline }
"instalado; fgd " + (Get-Item "$g\bin\win64\hammerplusplus\hammertools.fgd").LastWriteTime.ToString("HH:mm:ss")'
if [ $COMPILE = 1 ]; then PS="$PS"'
$o = & "$bin\ht-vbsp.exe" -game "$g\garrysmod" "$m\test_stairs" 2>&1 | Out-String; ($o -split "`n" | ? { $_ -match "ht-vbsp:|leaked|unbounded|aviso" } | % { $_.Trim() })
& "$g\bin\win64\vvis.exe" -game "$g\garrysmod" "$m\test_stairs" 2>&1 | Out-Null; & "$g\bin\win64\vrad.exe" -game "$g\garrysmod" "$m\test_stairs" 2>&1 | Out-Null
Copy-Item "$m\test_stairs.bsp" "$g\garrysmod\maps\test_stairs.bsp" -Force; "maps bsp: " + [math]::Round((Get-Item "$g\garrysmod\maps\test_stairs.bsp").Length/1KB) + " KB"
& "$bin\ht-preview.cmd" "$m\test_stairs" 2>&1 | Out-Null; "preview regenerado"'; fi
if [ $RELOAD = 1 ]; then PS="$PS"'
Start-Process -FilePath "$g\bin\win64\gmod.exe" -WorkingDirectory $g -ArgumentList "-hijack","-game","`"$g\garrysmod`"","+map","test_stairs"; "gmod recarregado"'; fi
~/vms/qga.sh "$PS" 900 2>/dev/null | grep -v -E "CLIXML|^<Objs"
