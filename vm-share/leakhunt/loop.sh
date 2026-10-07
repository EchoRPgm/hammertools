for i in $(seq 1 ${1:-30}); do ./run.sh >/dev/null; ../../.venv/bin/python step.py 2>/dev/null || break; done
