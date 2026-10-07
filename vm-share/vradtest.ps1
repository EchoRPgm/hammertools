$g='C:\Program Files (x86)\Steam\steamapps\common\GarrysMod'
$src="$g\sourcesdk_content\garrysmod\mapsrc\rp_surdonoso_w_tj.bsp"
$d="C:\ht\vtC"; Remove-Item $d -Recurse -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force $d | Out-Null
Copy-Item $src "$d\rp_surdonoso_w_tj.bsp" -Force
& "$g\bin\win64\vrad.exe" -fast -game "$g\garrysmod" "$d\rp_surdonoso_w_tj" *> "$d\vrad.txt"
"done" | Out-File "$d\done.txt"
