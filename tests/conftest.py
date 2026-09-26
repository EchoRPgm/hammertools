import pytest
from srctools import VMF, Vec


def base_room(size: int = 1024, height: int = 512) -> VMF:
    """Sala fechada (hollow), spawn e luz. Sem leaks."""
    v = VMF()
    for s in v.make_hollow(Vec(-size, -size, -64), Vec(size, size, height), thick=64,
                           mat="tools/toolsnodraw", inner_mat="dev/dev_measuregeneric01b"):
        v.add_brush(s)
    v.create_ent("info_player_start", origin="0 0 8")
    # 4 luzes fortes nos quadrantes + 1 central: sala grande precisa disso pra não parecer fullbright
    half = size // 2
    for x, y in ((-half, -half), (half, -half), (-half, half), (half, half)):
        v.create_ent("light", origin=f"{x} {y} {height - 64}", _light="255 244 220 600", _quadratic_attn="1", _fifty_percent_distance="512", _zero_percent_distance="1600")
    v.create_ent("light", origin=f"0 0 {height - 64}", _light="255 255 255 400", _quadratic_attn="1", _fifty_percent_distance="512", _zero_percent_distance="1600")
    return v


@pytest.fixture
def room() -> VMF:
    return base_room()
