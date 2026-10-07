import sys, numpy as np
from srctools.keyvalues import Keyvalues
from srctools.vmf import VMF
from srctools import Vec
from hammertools import seal
src,dst=sys.argv[1],sys.argv[2]
with open(src,encoding='utf-8',errors='replace') as f: v=VMF.parse(Keyvalues.parse(f))
X0,X1,Y0,Y1,Z0,Z1=-2149,2200,-16352,-15248,-560,540
T=16
slabs=[((X0-T,Y0-T,Z0-T),(X0,Y1,Z1+T)),   # oeste
       ((X1,Y0-T,Z0-T),(X1+T,Y1,Z1+T)),   # leste
       ((X0,Y0-T,Z0-T),(X1,Y0,Z1+T)),     # sul
       ((X0,Y0,Z0-T),(X1,Y1,Z0)),         # fundo
       ((X0,Y0,Z1),(X1,Y1,Z1+T)),         # teto
       # norte, só abaixo da rua (acima disso é a seção antiga, selada); contorna o quarto vermelho (se fecha sozinho)
       ((X0,Y1,Z0),(-353,Y1+T,-380)),
       ((61,Y1,Z0),(1343,Y1+T,-380)),
       ((1343,Y1,Z0-T),(X1,Y1+T,Z1+T)),   # a seção antiga recua pra y -14843 a leste de x 1343
       ((-353,Y1,Z0),(61,Y1+T,-519)),
       ((-353,Y1,-384),(-343,Y1+T,-380)), ((51,Y1,-384),(61,Y1+T,-380))]  # frestas de 4u em cima das paredes do quarto
for lo,hi in slabs:
    seal.add_plug(v,Vec(*lo),Vec(*hi),'tools/toolsskybox')
# sobreposições com brushes que existem
for lo,hi in slabs:
    for e in [None]+list(v.entities):
        for s in (v.brushes if e is None else e.solids):
            a,b=s.get_bbox()
            if all(a[k]<hi[k]-0.01 and b[k]>lo[k]+0.01 for k in range(3)) and not (tuple(a)==lo and tuple(b)==hi):
                print('sobrepõe',lo,hi,'<->',s.id,a,b,sorted({x.mat for x in s.sides})[:2])
with open(dst,'w',encoding='utf-8') as f: v.export(f)
