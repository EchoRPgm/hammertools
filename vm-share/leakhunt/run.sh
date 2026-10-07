#!/bin/bash
G=/home/wanso/.local/share/Steam/steamapps/common/GarrysMod
M=/home/wanso/hammer-tools/vm-share/leakhunt/hunt
W="Z:$(echo $G/garrysmod | tr / '\\')"; MW="Z:$(echo $M | tr / '\\')"
export WINEDEBUG=-all
rm -f $M.lin
t0=$(date +%s)
wine $G/bin/win64/vbsp.exe -leaktest -game "$W" "$MW" > $M.vbsp.log 2>&1
echo "vbsp rc=$? $(( $(date +%s)-t0 ))s"
grep -i "leaked" $M.vbsp.log; [ -f $M.lin ] && cat $M.lin
