#!/bin/bash
# Roda o Hammer++ dentro do prefixo Proton do Garry's Mod (appid 4000)
set -e
STEAM="$HOME/.local/share/Steam"
GMOD="$STEAM/steamapps/common/GarrysMod"
PROTON="$STEAM/steamapps/common/Proton - Experimental/proton"
EXE="$GMOD/bin/win64/hammerplusplus.exe"

[ -f "$EXE" ] || { echo "hammerplusplus.exe não encontrado em $GMOD/bin/win64"; exit 1; }
[ -d "$STEAM/steamapps/compatdata/4000" ] || { echo "Prefixo Proton do GMod não existe. Abre o GMod uma vez via Proton primeiro."; exit 1; }

export STEAM_COMPAT_CLIENT_INSTALL_PATH="$STEAM"
export STEAM_COMPAT_DATA_PATH="$STEAM/steamapps/compatdata/4000"
export SteamAppId=4000
export SteamGameId=4000
cd "$GMOD/bin/win64"
exec "$PROTON" run "$EXE" "$@"
