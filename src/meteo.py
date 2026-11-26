"""Meteorologia horária em Braga (precipitação, chuva, temperatura).

Fonte: Open-Meteo (https://open-meteo.com), gratuita e sem registo. A API
devolve os valores hora a hora dos últimos dias (até 92), por isso este
script pode correr a qualquer altura: não se perdem dias se falhar uma vez.

Os dados são acrescentados a um CSV; horas repetidas ficam com o valor mais
recente (os modelos meteorológicos corrigem os valores das horas passadas).

Uso:
    python src/meteo.py                       # últimos 3 dias -> dados/meteo/meteo_braga.csv
    python src/meteo.py --dias 30             # últimos 30 dias (para recuperar o período todo)
    python src/meteo.py --saida outro.csv
    python src/meteo.py --juntar PASTA        # junta os CSV recolhidos pelo GitHub num só
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "dados" / "meteo" / "meteo_braga.csv"

# Campus Camões da UCP (a grelha do modelo tem alguns km, por isso serve para toda a cidade)
LAT, LON = 41.554481, -8.419050

URL = "https://api.open-meteo.com/v1/forecast"
VARIAVEIS = ["precipitation", "rain", "temperature_2m", "weather_code"]
NOMES = {
    "time": "hora",
    "precipitation": "precipitacao_mm",
    "rain": "chuva_mm",
    "temperature_2m": "temperatura_c",
    "weather_code": "codigo_tempo",
}


def obter(dias: int, url: str = URL) -> pd.DataFrame:
    """Pede os últimos `dias` dias de dados horários (hora de Lisboa)."""
    params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": ",".join(VARIAVEIS),
        "past_days": dias,
        "forecast_days": 1,
        "timezone": "Europe/Lisbon",
    }
    pedido = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "tub-projeto/1.0 (projeto academico, LCDA - UCP Braga)"},
    )
    with urllib.request.urlopen(pedido, timeout=30) as resp:
        dados = json.load(resp)
    if "hourly" not in dados:
        raise RuntimeError(f"resposta inesperada: {str(dados)[:200]}")

    df = pd.DataFrame(dados["hourly"]).rename(columns=NOMES)
    df["hora"] = pd.to_datetime(df["hora"])
    # Fica só com horas já passadas (o resto é previsão)
    agora = pd.Timestamp.now(tz="Europe/Lisbon").tz_localize(None)
    return df[df["hora"] <= agora]


def juntar(novo: pd.DataFrame, ficheiro: Path) -> pd.DataFrame:
    """Acrescenta ao CSV existente; em horas repetidas fica o valor mais recente."""
    if ficheiro.exists():
        antigo = pd.read_csv(ficheiro, parse_dates=["hora"])
        novo = pd.concat([antigo, novo], ignore_index=True)
    return (novo.drop_duplicates(subset="hora", keep="last")
                .sort_values("hora")
                .reset_index(drop=True))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dias", type=int, default=3, help="dias para trás (1-92)")
    p.add_argument("--saida", type=Path, default=SAIDA)
    p.add_argument("--juntar", type=Path, metavar="PASTA",
                   help="não pede dados: junta todos os CSV desta pasta em --saida")
    p.add_argument("--url", default=URL, help=argparse.SUPPRESS)
    args = p.parse_args()

    if args.juntar:
        ficheiros = sorted(args.juntar.glob("*.csv"))
        if not ficheiros:
            print(f"Sem ficheiros CSV em {args.juntar}")
            return 1
        # Por ordem de nome = ordem de recolha, para que o valor mais recente prevaleça
        novo = pd.concat([pd.read_csv(f, parse_dates=["hora"]) for f in ficheiros], ignore_index=True)
        tabela = juntar(novo, args.saida)
        args.saida.parent.mkdir(parents=True, exist_ok=True)
        tabela.to_csv(args.saida, index=False)
        print(f"{len(ficheiros)} ficheiros juntos -> {args.saida}: {len(tabela)} horas")
        return 0

    if not 1 <= args.dias <= 92:
        p.error("--dias tem de estar entre 1 e 92")

    try:
        novo = obter(args.dias, args.url)
    except Exception as erro:  # rede, API em baixo, etc.
        print(f"Erro ao obter a meteorologia: {erro}")
        return 1

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    tabela = juntar(novo, args.saida)
    tabela.to_csv(args.saida, index=False)

    chuva = novo[novo["precipitacao_mm"] > 0]
    print(f"{len(novo)} horas obtidas ({novo['hora'].min():%d/%m %H:%M} a {novo['hora'].max():%d/%m %H:%M}), "
          f"{len(chuva)} com precipitação, total {novo['precipitacao_mm'].sum():.1f} mm")
    print(f"{args.saida}: {len(tabela)} horas no total")
    return 0


if __name__ == "__main__":
    sys.exit(main())