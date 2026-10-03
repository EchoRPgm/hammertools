#!/bin/bash
# Publica uma versão: tools/release.sh X.Y.Z
# Confere árvore limpa e testes, grava a versão, commita, cria a tag vX.Y.Z e dá push; o workflow
# .github/workflows/release.yml testa de novo, gera o wheel e publica o release.
set -euo pipefail
cd "$(dirname "$0")/.."
v="${1:?uso: tools/release.sh X.Y.Z}"
[[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "versão inválida: $v"; exit 1; }
[ "$(git branch --show-current)" = main ] || { echo "precisa estar na main"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "há mudanças não commitadas"; exit 1; }
git rev-parse -q --verify "refs/tags/v$v" >/dev/null && { echo "tag v$v já existe"; exit 1; }
.venv/bin/python -m pytest -q
sed -i "s/^__version__ = \".*\"/__version__ = \"$v\"/" hammertools/__init__.py
git commit -qm "chore(release): v$v" hammertools/__init__.py
git tag -a "v$v" -m "v$v"
git push -q origin main "v$v"
echo "tag v$v enviada; acompanhe: gh run watch \$(gh run list -w release -L1 --json databaseId -q '.[0].databaseId')"
