import re, sys, json
from srctools.keyvalues import Keyvalues
from srctools.vmf import VMF
from srctools import Vec
from hammertools import lint
log=open('hunt.vbsp.log',encoding='latin-1').read()
m=re.search(r"Entity (\S+) \((\S+) (\S+) (\S+)\) leaked",log)
if not m: print("SEM LEAK"); sys.exit(2)
cls=m[1]; P=Vec(float(m[2]),float(m[3]),float(m[4]))
pts=[Vec(*map(float,l.split())) for l in open('hunt.lin')]
with open('hunt.vmf',encoding='utf-8',errors='replace') as f: v=VMF.parse(Keyvalues.parse(f))
res=lint.Resources()
R=256
near=0
for s in v.brushes:
    a,b=s.get_bbox()
    if all(a[k]-R<=P[k]<=b[k]+R for k in range(3)) and lint._seals(s,res): near+=1
print(f"{cls} {P} pontos={len(pts)} brushes_selantes_256u={near}")
if near or len(pts)>2:
    for p in pts[:12]: print('  ',p)
    sys.exit(1)
# solta no vazio: remove ela e todas as entidades pontuais a 160u (mesma luminária)
rm=[]
for e in list(v.entities):
    o=e['origin']
    if e.solids or not o: continue
    if (Vec.from_str(o)-P).mag()<=160:
        rm.append((e['classname'],o,e['targetname'],e['model'])); v.remove_ent(e)
with open('removidas.jsonl','a') as f:
    for r in rm: f.write(json.dumps(r)+'\n')
print('  removidas',len(rm))
with open('hunt.vmf','w',encoding='utf-8') as f: v.export(f)
