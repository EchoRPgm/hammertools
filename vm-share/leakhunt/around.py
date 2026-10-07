import sys
from srctools.keyvalues import Keyvalues
from srctools.vmf import VMF
from hammertools import lint
x0,y0,z0,x1,y1,z1=map(float,sys.argv[1:7])
with open('hunt.vmf',encoding='utf-8',errors='replace') as f: v=VMF.parse(Keyvalues.parse(f))
res=lint.Resources()
for e in [None]+list(v.entities):
  for s in (v.brushes if e is None else e.solids):
    a,b=s.get_bbox()
    if a.x<=x1 and b.x>=x0 and a.y<=y1 and b.y>=y0 and a.z<=z1 and b.z>=z0:
        print(s.id, e['classname'] if e else 'world', 'sela' if e is None and lint._seals(s,res) else '', a,b, sorted({f.mat for f in s.sides})[:2])
