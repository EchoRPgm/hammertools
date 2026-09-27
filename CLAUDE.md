# hammertools — contexto para o Claude

Geradores de geometria e entidades para o Hammer++ (Garry's Mod). Marcadores `ht_*` no editor → CLI Python reescreve o VMF. Repo privado: github.com/EchoRPgm/hammertools.

**Leia `ROADMAP.md` primeiro**: status por item, arquitetura, como usar no Hammer++ e as notas técnicas que custaram a descobrir (srctools, ladders, trem, cubemaps, leaks). Este arquivo só complementa.

## Estado (2026-09-27)

- Sprints 1–5 prontos e validados no jogo: escada (com playerclip), cerca (brush/prop com bbox do .mdl), corrimão, escada de mão (func_useableladder), arco, tubo/duto com cotovelos curvos, escada em curva, porta, luzes em fila, elevador, spawn room, cabo, trilho curvo com trem automático e estações, terreno (displacement), zonas (`ht_zone`).
- `ht_cubemaps` desativado (reflexos ruins no jogo); gerador existe, fora da fixture.
- Sprint 6: **lint completo pronto** (`ht lint`: texturas/modelos com VPK+addons+BSP, leak por voxel com pointfile, nodraw, duplicados, sobreposições, grid, I/O, t-junctions) com relatório HTML geral (`--html`, aba Painel primeiro); `ht content` (monta o addon de conteúdo do mapa); `ht optimize` (junta blocos fatiados); ht-vbsp recompila com `-notjunc` se estourar t-junctions. Pendente: abrir rp_surdonoso_w no Hammer++ da VM (Windows-MCP desconectado; precisa `/mcp`). Próximo: `ht detail` (mapa pronto), `ht lightmap`, `ht rename`; sprint 7 = `ht diff`, `ht retexture`, `ht pack`.
- 89 testes (`.venv/bin/python -m pytest -q`), leak test (`tools/leaktest.sh`, 5 mapas) e lint da fixture limpos.

## Fluxo de trabalho

- **VM Windows** (Hammer++ + GMod): `cd ~/vms && quickemu --vm windows-11-English-United-States.conf`. Servidor de arquivos pro deploy: `cd ~/hammer-tools/vm-share && python3 -m http.server 8090 --bind 0.0.0.0` (a VM acessa em http://10.0.2.2:8090).
- **Windows-MCP** (`windows-vm`, porta 8000): se a VM subir depois da sessão, rodar `/mcp` e reconectar. Trava em comandos longos; pra compile, deploy e destravar use `~/vms/qga.sh "<powershell>" [timeout]` (QEMU guest agent, roda como SYSTEM, caminhos explícitos `C:\Users\Quickemu\...`). `~/vms/qga-get.sh <caminho windows> <destino>` copia arquivo da VM.
- **Deploy**: `tools/fixture.py` (regenera o mapa de teste), `tools/deploy.sh [--no-compile] [--reload]` (pacote + FGD em cp1252 + compile + preview; `--reload` recarrega no GMod da VM). Hammer++ só relê FGD/sequências ao reabrir.
- **Mapa de teste**: `maps/test_stairs.vmf` gerado por `tools/fixture.py`. Laranja = pendente de validação, cinza claro = validado (dicionário `STATUS` no script). Compilado fica em `garrysmod\maps\test_stairs.bsp` na VM; pra testar no Linux, copiar com `qga-get.sh` pra `~/.local/share/Steam/steamapps/common/GarrysMod/garrysmod/maps/`.
- **Commits**: conventional commits em português, push direto na `main`.

## GMod no Linux (host)

- Roda **nativo** (o usuário achou a versão Proton bugada). O menu HTML falhava ("Menu failed to load": renderer do CEF não subia no container do Steam); corrigido com o GModPatchTool, guardado em `~/.local/share/gmodpatchtool/gmodpatchtool`. Se uma atualização do GMod quebrar o menu de novo: com o jogo fechado, `~/.local/share/gmodpatchtool/gmodpatchtool --skip-exit-prompt --no-sourcescheme`.
- Janela sem borda 2560x1080 (`ScreenNoBorder 1` em `garrysmod/videoconfig_linux.cfg`), melhor pro KDE Wayland.
- A pasta `bin/win64` do GMod do host tem restos do Hammer++ (tentativa via Proton, abandonada); inofensivos.

## Discussões que ficaram fora da linha ativa da conversa original (recuperadas do transcript)

- **Espaço "maior por dentro" (Tardis)**: opções no Source: teleporte com landmark (costura escondida), `point_camera` + `func_monitor` na porta, ou interior sobreposto com areaportals. Portal seamless de verdade (`linked_portal_door`) só existe no Portal 2 e derivados; no GMod o caminho é um addon Lua de "seamless portals" (render com `render.RenderView` + clip plane + stencil, travessia com transformação de posição/ângulo/velocidade, PVS com `AddOriginToPVS`). Espaço **realmente** não euclidiano (curvatura hiperbólica, tipo Hyperbolica/HyperRogue) é impossível no Source: exige engine própria com projeção no shader (Godot/Unity), física por geodésicas. Ficou como ideia, sem implementação.
- **Hammer++ num container Docker**: descartado em favor da VM.
- **GPU na VM**: o Windows da VM roda em software (sem aceleração 3D). Opções levantadas: passthrough VFIO da RTX 5070 (o Linux ficaria na iGPU) ou da iGPU Radeon do Ryzen (Linux fica com a 5070; sem saída de vídeo própria, exige Looking Glass/dummy plug; reset bug da iGPU AMD). Não implementado; o fluxo adotado é editar/compilar na VM e jogar no host.
- **sudo**: `faillock` bloqueou a conta após tentativas pelo `!` do Claude Code (sem TTY). Comandos com sudo: rodar num terminal normal.
- **Escada afunilada** (`taper`): largura interpolada do início ao fim, crescendo ou estreitando; modos `stepped` (blocos, sempre no grid) e `smooth` (trapézios). Planejado, não implementado; está em "Ideias fora do roadmap".
