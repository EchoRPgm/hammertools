"""Primitivas de brush. Tudo é construído axis-aligned e depois rotacionado com `place`."""
from __future__ import annotations

from srctools import VMF, Angle, Vec
from srctools.vmf import Solid

NODRAW = "tools/toolsnodraw"


def box(vmf: VMF, p1: Vec, p2: Vec, mat: str, top: str | None = None,
        nodraw: tuple[str, ...] = ()) -> Solid:
    """Caixa entre p1 e p2. `top` sobrescreve a face de cima; `nodraw` lista faces
    ("top","bottom","north","south","east","west") que recebem toolsnodraw.
    north/south = ±Y, east/west = ±X (antes de qualquer rotação)."""
    prism = vmf.make_prism(Vec(p1), Vec(p2), mat)
    if top:
        prism.top.mat = top
    for name in nodraw:
        getattr(prism, name).mat = NODRAW
    return prism.solid


def place(solids: list[Solid], origin: Vec, yaw: float) -> None:
    """Rotaciona em torno de (0,0,0) por yaw e translada pra origin. Aplica in-place."""
    ang = Angle(0, yaw, 0)
    for s in solids:
        s.localise(origin, ang)


def from_planes(vmf: VMF, specs: list[tuple[Vec | tuple, Vec | tuple, str]]) -> Solid:
    """Solid convexo a partir de planos. Cada spec = (ponto no plano, normal APONTANDO PRA FORA, material).
    srctools.Side.from_plane espera a normal pra dentro, por isso o sinal é invertido aqui."""
    from srctools.vmf import Side
    sides = [Side.from_plane(vmf, Vec(*p), -Vec(*n), m) for p, n, m in specs]
    return Solid(vmf, sides=sides)


def from_points(vmf: VMF, faces: list[tuple[Vec | tuple, Vec | tuple, Vec | tuple, str]]) -> Solid:
    """Solid a partir de faces com 3 pontos explícitos (ficam no grid se os pontos ficarem).
    Winding igual ao make_prism do srctools: cross(p2-p1, p3-p1) aponta PRA DENTRO do solid."""
    from srctools.vmf import Side
    sides = [Side(vmf, planes=[Vec(*a), Vec(*b), Vec(*c)], mat=m) for a, b, c, m in faces]
    for side in sides:
        side.reset_uv()  # eixos de textura alinhados ao plano; o padrão do srctools degenera em faces ±Y (face vermelha no jogo)
    return Solid(vmf, sides=sides)


def sloped_bar(vmf: VMF, x0: float, x1: float, y0: float, y1: float, z0: float, z1: float,
               thickness: float, mat: str) -> Solid:
    """Barra ao longo de X cuja base segue a reta (x0,z0)->(x1,z1); `thickness` é a espessura
    vertical. Caps verticais em x0 e x1, laterais em y0/y1. Serve pra corrimão/rampa."""
    t = thickness
    return from_points(vmf, [
        ((x0, y1, z0 + t), (x1, y1, z1 + t), (x1, y0, z1 + t), mat),  # topo
        ((x0, y0, z0), (x1, y0, z1), (x1, y1, z1), mat),              # base
        ((x0, y1, z0), (x1, y1, z1), (x1, y1, z1 + t), mat),          # lateral +Y
        ((x1, y0, z1), (x0, y0, z0), (x0, y0, z0 + t), mat),          # lateral -Y
        ((x1, y1, z1), (x1, y0, z1), (x1, y0, z1 + t), mat),          # cap x1
        ((x0, y1, z0 + t), (x0, y0, z0 + t), (x0, y0, z0), mat),      # cap x0
    ])


def to_world(local: Vec, origin: Vec, yaw: float) -> Vec:
    """Mesma transformação de `place`, para pontos (origens de entidades)."""
    return Vec(local) @ Angle(0, yaw, 0) + origin


def snap(p: Vec | tuple, grid: float = 1.0) -> Vec:
    """Arredonda cada coordenada pro grid (evita vértices fracionários em geometria curva)."""
    v = Vec(*p)
    return Vec(round(v.x / grid) * grid, round(v.y / grid) * grid, round(v.z / grid) * grid)


def place3d(solids: list[Solid], origin: Vec, pitch: float, yaw: float, roll: float = 0.0) -> None:
    """Como `place`, com pitch/roll (Source: pitch negativo = pra cima; roll gira Y->Z)."""
    ang = Angle(pitch, yaw, roll)
    for s in solids:
        s.localise(origin, ang)


def to_world3d(local: Vec, origin: Vec, pitch: float, yaw: float, roll: float = 0.0) -> Vec:
    return Vec(local) @ Angle(pitch, yaw, roll) + origin


def direction_angles(d: Vec) -> tuple[float, float]:
    """(pitch, yaw) que levam o eixo +X local até a direção `d`."""
    import math
    horiz = math.hypot(d.x, d.y)
    return -math.degrees(math.atan2(d.z, horiz)), math.degrees(math.atan2(d.y, d.x))


def ngon_prism(vmf: VMF, x0: float, x1: float, radius: float, sides: int, mat: str,
               grid: float = 1.0, mat_caps: str | None = None) -> Solid:
    """Prisma de seção regular (n lados) ao longo de X, eixo em (y,z)=(0,0). `radius` é o APÓTEMA
    (do eixo à face plana); um lado plano em cima e embaixo (sides=4 -> quadrado de lado 2*radius)."""
    import math
    caps = mat_caps or mat
    off = math.pi / sides  # gira meio passo pra deixar faces planas em cima/baixo
    rc = radius / math.cos(math.pi / sides)
    pts = [(math.cos(off + 2 * math.pi * i / sides) * rc, math.sin(off + 2 * math.pi * i / sides) * rc) for i in range(sides)]
    pts = [(round(y / grid) * grid, round(z / grid) * grid) for y, z in pts]
    faces = []
    # cap x0 (normal -X pra fora -> winding com cross pra +X): usa 3 vértices consecutivos
    faces.append(((x0, pts[0][0], pts[0][1]), (x0, pts[1][0], pts[1][1]), (x0, pts[2][0], pts[2][1]), caps))
    faces.append(((x1, pts[2][0], pts[2][1]), (x1, pts[1][0], pts[1][1]), (x1, pts[0][0], pts[0][1]), caps))
    for i in range(sides):
        (ya, za), (yb, zb) = pts[i], pts[(i + 1) % sides]
        faces.append(((x0, yb, zb), (x0, ya, za), (x1, ya, za), mat))
    return from_points(vmf, faces)


def quad_prism(vmf: VMF, quad: list[Vec], z0: float, z1: float, mat: str, mat_top: str | None = None,
               nodraw_bottom: bool = False, grid: float = 1.0) -> Solid:
    """Prisma vertical sobre um quadrilátero convexo `quad` (4 pontos XY em ordem anti-horária
    vista de cima), de z0 a z1. Vértices arredondados pro grid."""
    q = [snap(Vec(p.x, p.y, 0), grid) for p in quad]
    top = mat_top or mat
    bot = NODRAW if nodraw_bottom else mat
    faces = [
        ((q[0].x, q[0].y, z1), (q[2].x, q[2].y, z1), (q[1].x, q[1].y, z1), top),   # topo (winding pra dentro = -Z)
        ((q[0].x, q[0].y, z0), (q[1].x, q[1].y, z0), (q[2].x, q[2].y, z0), bot),   # base
    ]
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        faces.append(((b.x, b.y, z0), (a.x, a.y, z0), (a.x, a.y, z1), mat))
    return from_points(vmf, faces)


def from_points_auto(vmf: VMF, faces: list[tuple]) -> Solid:
    """from_points que corrige o winding sozinho: se o centróide dos pontos não ficar dentro,
    inverte todas as faces. Útil pra geometria gerada numericamente (varreduras, cotovelos)."""
    s = from_points(vmf, faces)
    pts = [Vec(*p) for f in faces for p in f[:3]]
    c = sum(pts, Vec()) / len(pts)
    if not s.point_inside(c):
        s = from_points(vmf, [(a, cc, b, m) for a, b, cc, m in faces])
    return s


def sweep_piece(vmf: VMF, ring_a: list[Vec], ring_b: list[Vec], mat: str, mat_caps: str | None = None,
                grid: float = 1.0) -> Solid:
    """Solid entre dois anéis correspondentes (n pontos cada): 2 caps + n faces laterais.
    Faces são PLANOS (3 pontos), então quads levemente não planares não são problema."""
    n = len(ring_a)
    a = [snap(p, grid) for p in ring_a]
    b = [snap(p, grid) for p in ring_b]
    caps = mat_caps or mat
    faces = [(a[0], a[1], a[2], caps), (b[2], b[1], b[0], caps)]
    for i in range(n):
        j = (i + 1) % n
        faces.append((a[j], a[i], b[i], mat))
    return from_points_auto(vmf, faces)


def wall_piece(vmf: VMF, oa: Vec, ob: Vec, oc: Vec, od: Vec, ia: Vec, ib: Vec, ic: Vec, id_: Vec,
               mat: str, mat_in: str | None = None, grid: float = 1.0) -> Solid:
    """Hexaedro de parede: quad externo (oa,ob,oc,od) e interno correspondente (ia,ib,ic,id)."""
    oa, ob, oc, od, ia, ib, ic, id_ = (snap(p, grid) for p in (oa, ob, oc, od, ia, ib, ic, id_))
    mi = mat_in or mat
    faces = [
        (oa, ob, oc, mat),      # externa
        (ic, ib, ia, mi),       # interna
        (oa, ia, ib, mat), (ob, ib, ic, mat), (oc, ic, id_, mat), (od, id_, ia, mat),  # bordas
    ]
    return from_points_auto(vmf, faces)


def rotate_about(v: Vec, axis: Vec, ang_rad: float) -> Vec:
    """Rodrigues: gira `v` em torno do eixo unitário `axis`."""
    import math
    k = Vec(axis).norm()
    return v * math.cos(ang_rad) + Vec.cross(k, v) * math.sin(ang_rad) + k * (k.dot(v) * (1 - math.cos(ang_rad)))


def from_points_oriented(vmf: VMF, faces: list[tuple], centroid: Vec | None = None) -> Solid:
    """from_points orientando CADA face por um ponto interior (`centroid`; default = média dos pontos
    das faces, que só serve se nenhum ponto auxiliar fora do solid aparecer nas faces).
    cross(p2-p1, p3-p1) fica apontando pro ponto interior (convenção do srctools)."""
    if centroid is None:
        pts = [Vec(*p) for f in faces for p in f[:3]]
        centroid = sum(pts, Vec()) / len(pts)
    c = Vec(centroid)
    fixed = []
    for a, b, cc, m in faces:
        a, b, cc = Vec(*a), Vec(*b), Vec(*cc)
        n = Vec.cross(b - a, cc - a)
        fixed.append((a, b, cc, m) if n.dot(c - a) > 0 else (a, cc, b, m))
    return from_points(vmf, fixed)


def ring_wall_piece(vmf: VMF, ring_a: list[Vec], ring_b: list[Vec], inner_a: list[Vec], inner_b: list[Vec],
                    ca: Vec, cb: Vec, i: int, mat: str, mat_in: str | None = None, grid: float = 1.0) -> Solid:
    """Parede i de uma seção oca entre os anéis A e B, construída como FATIA: as laterais são planos
    radiais (pelo centro do anel) que passam pelo MEIO das arestas vizinhas, então cada parede sobrepõe
    metade das duas ao lado. Em curvas os planos radiais ficam levemente inclinados e, sem sobreposição,
    sobra uma fresta na aresta do canto (leak confirmado por pointfile); com sobreposição não há costura
    fina. Brushes de mundo sobrepostos são legais (vbsp faz a união)."""
    n = len(ring_a); j = (i + 1) % n; h = (i - 1) % n; k = (i + 2) % n
    oa, ob, oc, od = (snap(ring_a[i], grid), snap(ring_a[j], grid), snap(ring_b[j], grid), snap(ring_b[i], grid))
    ia, ib, ic, id_ = (snap(inner_a[i], grid), snap(inner_a[j], grid), snap(inner_b[j], grid), snap(inner_b[i], grid))
    ca, cb = snap(ca, grid), snap(cb, grid)
    m_lo = snap((ring_a[h] + ring_a[i]) / 2, grid)   # meio da aresta anterior (anel A)
    m_hi = snap((ring_a[j] + ring_a[k]) / 2, grid)   # meio da aresta seguinte (anel A)
    mi = mat_in or mat
    faces = [
        (oa, ob, oc, mat),      # externa
        (ia, ib, ic, mi),       # interna
        (oa, ob, ca, mat),      # cap anel A
        (od, oc, cb, mat),      # cap anel B
        (ca, m_lo, cb, mat),    # radial baixo: meio da aresta anterior (sobrepõe a parede i-1)
        (ca, m_hi, cb, mat),    # radial alto: meio da aresta seguinte (sobrepõe a parede i+1)
    ]
    corners = (oa, ob, oc, od, ia, ib, ic, id_)
    return from_points_oriented(vmf, faces, centroid=sum(corners, Vec()) / 8)  # os centros dos anéis NÃO entram
