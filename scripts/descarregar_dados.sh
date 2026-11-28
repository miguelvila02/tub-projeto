#!/usr/bin/env bash
# Descarrega para dados/gtfs_rt/brutos/ os dados de TODAS as recolhas feitas no
# GitHub Actions, diretamente pela API (artefactos "gtfs-rt-*").
# Os artefactos já descarregados ficam registados em
# dados/gtfs_rt/brutos/.artefactos_descarregados e não se repetem.
#
# Uso (na raiz do projeto):  bash scripts/descarregar_dados.sh
set -euo pipefail

destino="dados/gtfs_rt/brutos"
registo="$destino/.artefactos_descarregados"
mkdir -p "$destino"
touch "$registo"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
echo "Repositório: $repo"
echo "A listar artefactos..."

# Uma linha por artefacto: id nome tamanho
gh api "repos/$repo/actions/artifacts?per_page=100" --paginate \
   -q '.artifacts[] | select(.expired == false and (.name | startswith("gtfs-rt-"))) | "\(.id) \(.name) \(.size_in_bytes)"' \
   > "$tmp/lista.txt"

total=$(wc -l < "$tmp/lista.txt")
echo "Artefactos no GitHub: $total"

novos=0
while read -r id nome tamanho; do
    [ -n "$id" ] || continue
    if grep -qx "$id" "$registo"; then
        continue                                   # já descarregado antes
    fi
    zipf="$tmp/$id.zip"
    if gh api "repos/$repo/actions/artifacts/$id/zip" > "$zipf" 2> "$tmp/erro.txt"; then
        python -m zipfile -e "$zipf" "$tmp/$id"
        n=$(find "$tmp/$id" -type f -name '*.pb.gz' | wc -l)
        printf '  %-40s %8s bytes  %4d ficheiros .pb.gz\n' "$nome" "$tamanho" "$n"
        echo "$id" >> "$registo"
        novos=$((novos + 1))
    else
        printf '  %-40s ERRO: %s\n' "$nome" "$(head -c 200 "$tmp/erro.txt")"
    fi
done < "$tmp/lista.txt"
echo "Artefactos novos descarregados: $novos"

# Copia os .pb.gz para destino/AAAA-MM-DD/, sem substituir os que já existem
copiados=0
while IFS= read -r -d '' f; do
    dia="$(basename "$(dirname "$f")")"
    mkdir -p "$destino/$dia"
    if [ ! -e "$destino/$dia/$(basename "$f")" ]; then
        cp "$f" "$destino/$dia/"
        copiados=$((copiados + 1))
    fi
done < <(find "$tmp" -type f -name '*.pb.gz' -path '*/20??-??-??/*' -print0)
echo "Ficheiros novos copiados: $copiados"

# Logs e meteorologia
mkdir -p "$destino/logs" "$destino/meteo"
find "$tmp" -type f -name 'recolha_*.log' -exec cp -n {} "$destino/logs/" \; 2>/dev/null || true
find "$tmp" -type f -name 'meteo_*.csv'   -exec cp -n {} "$destino/meteo/" \; 2>/dev/null || true

echo
echo "Dias disponíveis em $destino:"
for d in "$destino"/20??-??-??; do
    [ -d "$d" ] || continue
    n_tu=$(find "$d" -name 'trip_updates_*.pb.gz' | wc -l)
    n_vp=$(find "$d" -name 'vehicle_positions_*.pb.gz' | wc -l)
    tamanho=$(du -sh "$d" | cut -f1)
    printf '  %s   %4d trip_updates   %4d vehicle_positions   %s\n' "$(basename "$d")" "$n_tu" "$n_vp" "$tamanho"
done

# Meteorologia: junta os CSV de cada execução num só ficheiro
if compgen -G "$destino/meteo/*.csv" > /dev/null; then
    echo
    python src/meteo.py --juntar "$destino/meteo"
fi