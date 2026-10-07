"""Fecha o rp_surdonoso_w_new de verdade: casca de skybox em volta da área nova do sul + lascas de 0,4u preenchidas.
Tudo no visgroup 'fechamento_sul' (visível no Hammer)."""
import sys
from srctools import Vec
from hammertools import lint, seal
from hammertools.core import vmf as vmfio
src,dst=sys.argv[1],sys.argv[2]
v=vmfio.load(src)
vg=vmfio._visgroup(v,'fechamento_sul',(255,120,0)).id
X0,X1,Y0,Y1,Z0,Z1,T=-2149,2200,-16352,-15248,-560,540,16
SW=float(sys.argv[3]) if len(sys.argv)>3 else -550   # início (x) da parede/céu da borda sul do mapa
slabs=[((X0-T,Y0,Z0-T),(X0,Y1,Z1+T)),          # oeste
       ((X1,Y0,Z0-T),(X1+T,Y1,Z1+T)),          # leste
       ((X0,Y0,Z0-T),(X1,Y1,Z0)),              # fundo
       ((X0,Y0,Z1),(X1,Y1,Z1+T)),              # teto
       # sul (dentro de ±16352): onde não há parede do mapa, altura toda; entre x -550 e 1194 só abaixo e acima dela
       ((X0-T,Y0,Z0-T),(SW,Y0+T,Z1+T)),
       ((1194,Y0,Z0-T),(X1+T,Y0+T,Z1+T)),
       ((SW,Y0,Z0-T),(1134,Y0+T,-405)),        # embaixo dos pisos (topo em -380)
       ((1134,Y0,Z0-T),(1194,Y0+T,-380)),        # sem piso aqui: até a parede
       ((SW,Y0,306),(1194,Y0+T,Z1+T)),
       # norte, só abaixo da rua (acima é a parede sul da seção antiga); contorna o quarto vermelho, que se fecha sozinho
       # (embaixo de piso a peça para na face de baixo dele: topo coplanar com o piso trocaria a faixa por céu)
       ((X0,Y1,Z0),(-2085,Y1+T,-386)),
       ((-2085,Y1,Z0),(-353,Y1+T,-380)),
       ((61,Y1,Z0),(772,Y1+T,-380)),
       ((772,Y1,Z0),(1134,Y1+T,-405)),
       ((1134,Y1,Z0),(1343,Y1+T,-380)),
       ((-353,Y1,Z0),(-343,Y1+T,-519)),
       ((-343,Y1,Z0),(51,Y1+T,-527)),
       ((51,Y1,Z0),(61,Y1+T,-519)),
       ((-353,Y1,-384),(-343,Y1+T,-380)),      # frestas de 4u entre o topo das paredes do quarto e a parede de cima
       ((51,Y1,-384),(61,Y1+T,-380)),
       ((1343,Y1,Z0-T),(X1,Y1+T,Z1+T))]        # a leste de x 1343 a seção antiga recua pra y -14843
# buracos do próprio mapa na borda sul (antes davam direto na borda do mundo): nodraw, ficam dentro de parede
fill=[((1130,-16352,133),(1194,-16320,170))]   # topo da parede 6507513 (133) até o céu 6555451 (170)
made=[]
def ocupado(lo,hi):
    for b in v.brushes:
        a,c=b.get_bbox()
        if all(a[k]<hi[k]-0.01 and c[k]>lo[k]+0.01 for k in range(3)): return True
    return False
for lo,hi in fill:
    if ocupado(lo,hi): print('  buraco já fechado no mapa:',lo,hi); continue
    s=v.make_prism(Vec(*lo),Vec(*hi),mat='tools/toolsnodraw').solid
    s.visgroup_ids.add(vg); v.add_brush(s); made.append(s)
for lo,hi in slabs:
    s=v.make_prism(Vec(*lo),Vec(*hi),mat='tools/toolsskybox').solid
    s.visgroup_ids.add(vg); v.add_brush(s); made.append(s)
sl=seal.close_slivers(v,lint.Resources())
seal_ids={g.id for g in v.vis_tree if g.name==seal.SEAL_VISGROUP}
for s in v.brushes:
    if s.visgroup_ids & seal_ids:
        s.visgroup_ids -= seal_ids; s.visgroup_ids.add(vg)
v.vis_tree[:]=[g for g in v.vis_tree if g.name!=seal.SEAL_VISGROUP]
print(f'casca: {len(made)} brushes; lascas: {len(sl)}')
# nenhuma peça da casca pode sobrepor face visível de brush existente
for s in made:
    lo,hi=s.get_bbox()
    for e in [None]+list(v.entities):
        for b in (v.brushes if e is None else e.solids):
            if b in made or vg in b.visgroup_ids: continue
            a,c=b.get_bbox()
            if all(a[k]<hi[k]-0.01 and c[k]>lo[k]+0.01 for k in range(3)):
                print('  sobrepõe',tuple(lo),tuple(hi),'<->',b.id,tuple(a),tuple(c),sorted({x.mat for x in b.sides})[:2])
vmfio.save(v,dst)
