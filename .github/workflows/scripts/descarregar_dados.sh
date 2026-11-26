#!/usr/bin/env bash
# Descarrega para dados/gtfs_rt/brutos/ todos os dias recolhidos pelo GitHub Actions.
# Os dias que já existem localmente não são substituídos.
#
# Uso (na raiz do projeto):  bash scripts/descarregar_dados.sh
set -euo pipefail
shopt -s nullglob

destino="dados/gtfs_rt/brutos"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "A descarregar artefactos do GitHub..."
gh run download --pattern 'gtfs-rt-*' --dir "$tmp"

mkdir -p "$destino"
for artefacto in "$tmp"/gtfs-rt-*; do
    # -n: não substitui ficheiros que já existam (filtra o aviso das versões recentes do cp)
    cp -rn "$artefacto"/. "$destino"/ 2>&1 | grep -v "non-portable" || true
done

echo "Dias disponíveis em $destino:"
find "$destino" -mindepth 1 -maxdepth 1 -type d -name '20*' -printf '  %f  ' -exec sh -c 'ls "$1" | grep -c "\.pb\.gz$"' _ {} \; | sort | sed 's/$/ ficheiros/'

# Meteorologia: junta os CSV de cada execução num só ficheiro
if [ -d "$destino/meteo" ]; then
    echo
    python src/meteo.py --juntar "$destino/meteo"
fi