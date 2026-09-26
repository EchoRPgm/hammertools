#!/bin/bash
# Gera os mapas de leak, manda pra VM, compila cada um com ht-vbsp e reporta leak/sem leak.
set -e
cd "$(dirname "$0")/.."
.venv/bin/python tools/leaktest.py
mkdir -p vm-share/leak && cp maps/leak/*.vmf vm-share/leak/
~/vms/qga.sh '$h="http://10.0.2.2:8090/leak"; $g="C:\Program Files (x86)\Steam\steamapps\common\GarrysMod"; $m="$g\sourcesdk_content\garrysmod\mapsrc\leak"; $bin="C:\Users\Quickemu\.local\bin"
New-Item -ItemType Directory -Force $m | Out-Null
foreach ($n in "leak_duct_square_rooms","leak_duct_square_capped","leak_duct_octagon_capped","leak_stairs_floor","leak_arch_wall") {
  Invoke-WebRequest "$h/$n.vmf" -OutFile "$m\$n.vmf" -UseBasicParsing
  Remove-Item "$m\$n.lin" -ErrorAction SilentlyContinue
  $o = & "$bin\ht-vbsp.exe" -game "$g\garrysmod" "$m\$n" 2>&1 | Out-String
  $leak = ($o -match "\*\*\*\* leaked \*\*\*\*") -or (Test-Path "$m\$n.lin")
  $brushes = (($o -split "`n" | ? { $_ -match "ht-vbsp: .*brush" }) -join "") -replace ".*-> ",""
  $err = (($o -split "`n" | ? { $_ -match "Error|degenerate|invalid|non-planar|Bad|\*\*\*" }) | Select -First 2) -join " / "
  "{0,-32} {1,-10} {2} {3}" -f $n, $(if ($leak) { "LEAK" } else { "ok" }), $brushes, $err
}' 400 2>/dev/null | grep -v -E "CLIXML|^<Objs"
