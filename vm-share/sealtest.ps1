$g='C:\Program Files (x86)\Steam\steamapps\common\GarrysMod'; $m="$g\sourcesdk_content\garrysmod\mapsrc"
Remove-Item C:\ht\seal.done,C:\ht\seal.txt -ErrorAction SilentlyContinue
Invoke-WebRequest http://10.0.2.2:8090/rp_surdonoso_w_new.vmf -OutFile "$m\rp_surdonoso_w_new.vmf" -UseBasicParsing
$env:HT_NO_UPDATE = "1"
& "C:\Users\Quickemu\AppData\Roaming\uv\tools\hammertools\Scripts\ht-vbsp.exe" -game "$g\garrysmod" "$m\rp_surdonoso_w_new" *> C:\ht\seal.txt
"rc=$LASTEXITCODE" | Out-File C:\ht\seal.done
