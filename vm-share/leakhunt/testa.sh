../../.venv/bin/python fechar.py ../rp_surdonoso_w_new.vmf fechado.vmf 2>&1 | grep -v RuntimeWarning
../../.venv/bin/python - 2>&1 <<'PY' | grep -v RuntimeWarning
from hammertools import extents
from hammertools.core import vmf as vmfio
v=vmfio.load('fechado.vmf'); extents.clamp(v); vmfio.save(v,'hunt.vmf')
PY
./run.sh
