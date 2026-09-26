# hammertools — roadmap e status

Toolkit de "addons" pro Hammer++ (Garry's Mod) sem tocar no binário: marcadores `ht_*` no editor → CLI Python reescreve o VMF. Um pacote, um CLI, um FGD.

Atualizado em 2026-09-26. Sprints 1, 2 e 3 concluídos e verificados na VM.

## Status por item

Legenda: ✅ pronto e verificado na VM · 🔧 implementado, em validação · ⬜ não iniciado

### Fase 0 — Fundação
| | Item |
|---|---|
| ✅ | Pacote `hammertools`, venv, `srctools`, CLI `ht` (`build`, `preview`, `lint`, `list-markers`) |
| ✅ | `core/vmf.py`: carregar/salvar preservando IDs, agrupar marcadores, visgroups `ht_generated` / `ht_preview` / `ht_markers` |
| ✅ | `core/brush.py`: caixa, prisma rotacionado (yaw ou pitch+yaw+roll), barra inclinada, prisma por pontos, n-gon, prisma sobre quadrilátero, snap pro grid |
| ✅ | `hammertools.fgd` registrado no Hammer++ (GameData2), com helper `line()` início→fim |
| ✅ | Compile transparente: `ht-vbsp.exe` no lugar do vbsp no gameconfig (qualquer modo de compile gera tudo) |
| ✅ | Preview no editor: `ht preview` gera a geometria real dentro do fonte (visgroup `ht_preview`); sequências "ht preview" e "ht preview clear" no Hammer++ |
| ✅ | Fixture `maps/test_stairs.vmf` (sala fechada, 5 luzes, todos os geradores); compila sem leak |

### Fase 1 — Geometria a partir de pontos
| | Entidades | Item |
|---|---|---|
| ✅ | `ht_stairs` + `_end` | Escada reta: largura, altura do degrau, sólida/flutuante, texturas, nodraw só nas faces ocultas, rampa de playerclip pelos narizes |
| ✅ | `ht_fence` + `_end` | Cerca modular: brush (postes + painéis, último cortado) ou prop (lê bbox do `.mdl`: espaçamento, yaw e altura automáticos) |
| ✅ | `ht_railing` + `_end` | Corrimão que segue a inclinação: postes, barra de cima e barra do meio |
| ✅ | `ht_ladder` + `_end` | Escada de mão GMod: volume `func_ladder` (toolsinvisibleladder) na frente do brush visual, com sobra acima do topo; yaw aponta pra parede |
| ✅ | `ht_arch` + `_end` | Arco/abóbada: semi-elipse em N segmentos, espessura radial, profundidade; altura auto = semicírculo |
| ✅ | `ht_pipe` + `_node` + `_end` | Tubo/duto por sequência de pontos: seção quadrada ou octogonal, sólido ou oco, cotovelos curvos tangentes em qualquer ângulo (horizontal ou vertical) |
| ✅ | `ht_stairs_curve` + `_ctrl` + `_end` | Escada em curva: bezier quadrática em XY, degraus sólidos ou flutuantes; sem playerclip ainda |
| ⬜ | `ht_rope` | Trilho de trem / cabo: caminho → `move_rope`/`keyframe_rope` encadeados ou brushes de trilho |
| ⬜ | `ht_terrain` | Terreno: retângulo → displacements com ruído ou heightmap PNG |

### Fase 2 — Entidades e lógica
| | Entidades | Item |
|---|---|---|
| 🔧 | `ht_door` | Porta completa num marcador: `prop_door_rotating` ou `func_door` de brush, batente, trigger opcional de abrir/fechar, I/O |
| 🔧 | `ht_lights` + `_end` | Iluminação em fila: `light_spot` ou `light` a cada N, com luminária `prop_static` opcional |
| 🔧 | `ht_elevator` + `_end` | Elevador: plataforma `func_door` (lip negativo = curso), botão a bordo (Toggle) e de chamada por andar (Open/Close), I/O pronta |
| 🔧 | `ht_spawnroom` + `_end` | Spawn room por retângulo: grade de `info_player_start` (GMod) ou `info_player_teamspawn` + `func_respawnroom` + `func_regenerate` (TF2) |
| ⬜ | `ht build --cubemaps` | Cubemaps automáticos por sala (flood-fill), sem marcador |
| ⬜ | `ht_zone` | Nav hints / clip: `func_nav_blocker`, `playerclip` em beiradas, `block_los` |

### Fase 3 — Lint e manutenção (`ht lint`, sem marcadores)
| | Item |
|---|---|
| ✅ | Pares de marcadores incompletos |
| ✅ | Outputs mirando targetname inexistente (case-insensitive, como o Source) |
| ✅ | Brushes fora do grid (mundo e entidades, um aviso por solid, displacements identificados) |
| ⬜ | Textura inexistente (ler VPKs), `prop_static` com modelo não-static, leak provável |
| ⬜ | Auto `func_detail` por regra de tamanho/textura (`ht detail`) |
| ⬜ | Normalizador de lightmap scale por textura (`ht lightmap`) |
| ⬜ | Renomeador por padrão com update de outputs (`ht rename`) |
| ⬜ | Brushes duplicados/sobrepostos e `nodraw` visível |

### Fase 4 — Colaboração e pipeline
| | Item |
|---|---|
| ⬜ | `ht diff a.vmf b.vmf` legível por ID de entidade/solid, config de `git difftool` |
| ⬜ | `ht retexture --map tabela.toml`: blockout (`dev/dev_measure*`) → texturas finais |
| ⬜ | `ht pack mapa.bsp`: lista assets custom e injeta com `bspzip` |

### Teste de leak (geometria gerada como fronteira do mapa)
`tools/leaktest.sh` gera 5 mapas (`tools/leaktest.py`) onde o gerado É o selo, compila cada um na VM com `ht-vbsp` e reporta `ok`/`LEAK` (por `**** leaked ****` e `.lin`):
duto quadrado atravessando a parede de duas salas com cotovelo; duto quadrado e octogonal tampados com o jogador dentro; escada sólida como piso entre dois níveis; arco numa divisória. Todos `ok` em 2026-09-26. Rodar sempre que mexer em `core/brush.py` ou nos geradores de geometria.

## Sprints

| Sprint | Entrega | Status |
|---|---|---|
| 1 | Fase 0 + escada reta | ✅ 2026-09-26 |
| 2 | Cerca, corrimão, escada de mão, lint básico | ✅ 2026-09-26 |
| 3 | Arco, tubo/duto, escada em curva | ✅ 2026-09-26 |
| 4 | Porta, luzes em fila, elevador, spawn room | 🔧 implementado 2026-09-26, validando na VM |
| 5 | Trilho/cabo, terreno, cubemaps, nav/clip | ⬜ |
| 6 | Auto detail, lightmap, rename, lint completo | ⬜ |
| 7 | Diff/merge, retexture, pack | ⬜ |

## Como usar (Hammer++ na VM)

1. Coloque os marcadores (ferramenta de entidade, `Shift+E`, digite `ht_` no combo Objects). Pares: `ht_x` com os parâmetros + `ht_x_end` só de posição, mesmo targetname. Tubo usa `ht_pipe_node` com `order`; escada em curva usa `_ctrl`.
2. Salve. Pra ver o resultado no editor: Run Map → Expert → **"ht preview"** → Go → File → Reload. Esconda/mostre pela checkbox do visgroup `ht_preview`. **"ht preview clear"** remove.
3. Compile normal (F9 → OK). O `ht-vbsp` limpa o preview do fonte, gera `mapsrc\build\<mapa>.vmf` e o BSP vai pra `garrysmod\maps`. Recarregue o mapa no Hammer++ depois (ele avisa que o arquivo mudou).
4. No jogo, `map <nome>` no console pra recarregar (ou `gmod.exe -hijack +map <nome>`).

## Arquitetura

- **Marcadores**: `ht_x` (início, todos os parâmetros) + auxiliares `ht_x_end` / `ht_x_node` / `ht_x_ctrl` (só posição e, no node, `order`), ligados pelo mesmo `targetname`. O FGD não tem campos condicionais, por isso classes separadas. `core/vmf.base_class` / `role_of` agrupam; keyvalue `role` antigo ainda é aceito.
- **Geradores**: `generators/<nome>.py` com `@register("ht_x")` e `generate(vmf, group) -> Result(solids, ents, warnings)`. Constroem em coordenadas locais (+X = do início pro fim) e posicionam com `brush.place` / `place3d`; entidades com `brush.to_world`.
- **Build**: `ht build fonte.vmf [-o saída] [--game dir]`: descarta `ht_preview`, roda geradores, adiciona em `ht_generated/<targetname>`, esconde marcadores em `ht_markers`, grava arquivo novo. Nunca sobrescreve o fonte; recusa `_built.vmf` como entrada.
- **Preview**: `ht preview fonte.vmf`: mesma geração, dentro do fonte em `ht_preview` (regenerado a cada rodada, marcadores visíveis). `--clear` remove.
- **ht-vbsp**: `hammertools.cli:vbsp_main`. Recebe os args do Hammer (`-game <dir> <path\file>`), limpa o preview do fonte (desligue com `HT_KEEP_PREVIEW=1`), faz o build em `build\`, chama o vbsp real (achado via `-game`, ou `HT_VBSP`) e copia `.bsp/.prt/.lin/.log` de volta pro lado do fonte.
- **Modelos**: `core/models.py` lê bbox de `.mdl` via `srctools.game.Game(gamedir).get_filesystem()`. Precisa da pasta do jogo (`--game`, `HT_GAME`, ou o `-game` do ht-vbsp).
- **Convenções**: unidades Hammer; vértices de geometria curva arredondados pro `grid` do marcador (padrão 1); saída sempre em arquivo novo; cada gerador tem entrada no FGD, módulo e teste.

## Notas técnicas (o que custou a descobrir)

- **srctools 2.7.0**: `Solid.export(include_groups=not _is_worldspawn)` está invertido e some com visgroups de brushes de mundo. `core/vmf.py` faz monkeypatch em `Solid.export`.
- **Normais**: `Side.normal()` aponta PRA DENTRO do solid. `PrismFace` do `make_prism`: west = face -X, east = +X, north = -Y, south = +Y. `Side.from_plane` recebe normal pra dentro e inventa pontos fora do grid; por isso geometria inclinada/curva usa `brush.from_points` com 3 pontos explícitos (winding igual ao `make_prism`: cross(p2-p1, p3-p1) pra dentro). Se `point_inside` do centro der False, o winding está invertido.
- **Eixos de textura**: `Side(planes=...)` do srctools sai com uaxis/vaxis padrão (`[0 1 0]`/`[0 0 -1]`), degenerado em faces com normal ±Y → o engine desenha a face VERMELHA. `brush.from_points` chama `reset_uv()` em cada face. Sintoma no jogo: face vermelha lisa (não é textura faltando, que seria xadrez rosa/preto).
- **Entidades de brush**: `core/ents.brush_ent` cria `func_*`/`trigger_*` com os solids DENTRO da entidade (nunca no mundo); `ents.out` adiciona output. Elevador = `func_door` com `movedir -90 0 0`, `wait -1` e `lip = espessura − curso` (lip negativo estende o curso), botão a bordo com `parentname`.
- **Ângulos**: `Vec @ Angle(pitch, yaw, roll)`; pitch negativo = pra cima; yaw 90 = +Y; roll 90 leva Y→Z.
- **Hammer++**: `parms` das sequências não aceita aspas aninhadas → wrappers `.cmd` (`ht-build.cmd`, `ht-preview.cmd`, `ht-preview-clear.cmd` em `%USERPROFILE%\.local\bin`) recebem `$path\$file` e montam as aspas. Sequências e FGD são lidos só na abertura do Hammer++.
- **GMod**: escada é o brush `func_ladder` (estilo CS/HL2DM, textura `tools/toolsinvisibleladder`); `func_useableladder` do HL2 NÃO funciona no GMod (testado: jogador não sobe). Executável do jogo é `bin\win64\gmod.exe`.
- **Playerclip da escada**: reta dos narizes (inclinação h/d) de (-d, 0) a (run-d, rise), depois plana até run. Flutuante: laje inclinada de espessura `tread` logo abaixo, pra não fechar o vão. Só jogadores (não é `npc_clip`).
- **Prop fence**: `props_c17/fence01a` = 134u no eixo Y, origem no centro (z −54..54). Sem bbox o gerador avisa e usa 64/0/0.
- **Cotovelos do tubo**: arco tangente aos dois trechos (raio `bend_radius`, tangente T = Rb·tan(θ/2) descontada dos retos), `bend_segments` pedaços por 90°. Cada pedaço é `brush.sweep_piece` (2 anéis correspondentes → caps + n planos laterais; quads não planares não importam porque face de VMF é plano de 3 pontos). Oco: `ring_wall_piece` por lado = fatia com laterais em planos RADIAIS (pelo centro do anel), compartilhados com as paredes vizinhas; hexaedro por pontos (`wall_piece`) deixava frestas na costura reto→cotovelo do octógono (leak confirmado por pointfile). `from_points_auto` corrige winding pelo centróide. `radius` do tubo é o apótema (face plana), não o raio circunscrito.
- **Windows-MCP**: processa um comando por vez e trava em comandos longos (compile, COM). Pra isso existe `~/vms/qga.sh "<powershell>" [timeout]` (QEMU guest agent; roda como SYSTEM, usar caminhos `C:\Users\Quickemu\...`). Destravar: `schtasks /End` + kill python + `schtasks /Run /TN windows-mcp-server`. `~/vms/qga-get.sh` copia arquivo da VM pro host.
- **vvis na VM**: usar sempre `vvis -fast` na fixture; o vvis completo com os cotovelos octogonais leva dezenas de minutos em software render e dois vvis simultâneos travam a VM.
- **Deploy na VM**: copiar `hammertools/` + `pyproject.toml` pra `vm-share/hammertools_pkg/`, zipar (`shutil.make_archive`), servido em `http://10.0.2.2:8090`; na VM `uv tool install --force <pasta>` e copiar o FGD pra `bin\win64\hammerplusplus\`. Reiniciar o Hammer++ depois.

## Ideias fora do roadmap

- Escada afunilada (largura interpolada entre início e fim).
- Playerclip pra escada em curva (wedges por degrau).
- Preview ao vivo é impossível sem plugin no binário; o ciclo é salvar → preview → reload.
