"""Leitura e verificação dos dados GTFS dos TUB.

Uso:
    python src/gtfs.py              # verifica dados/gtfs/
    python src/gtfs.py caminho/     # verifica outra pasta
"""
from pathlib import Path
import sys

import pandas as pd

PASTA_GTFS = Path(__file__).resolve().parent.parent / "dados" / "gtfs"

OBRIGATORIOS = ["agency", "stops", "routes", "trips", "stop_times", "calendar"]
OPCIONAIS = ["calendar_dates", "shapes", "fare_attributes", "fare_rules"]


def carregar_gtfs(pasta: Path = PASTA_GTFS) -> dict[str, pd.DataFrame]:
    """Lê todos os ficheiros GTFS da pasta para um dicionário de DataFrames.

    Todas as colunas são lidas como texto, para não perder zeros à esquerda
    nos identificadores; as conversões fazem-se depois, quando forem precisas.
    """
    pasta = Path(pasta)
    tabelas = {}
    for nome in OBRIGATORIOS + OPCIONAIS:
        ficheiro = pasta / f"{nome}.txt"
        if ficheiro.exists():
            tabelas[nome] = pd.read_csv(ficheiro, dtype=str, encoding="utf-8-sig")
    return tabelas


def hora_para_minutos(hora: str) -> int:
    """Converte 'HH:MM:SS' em minutos desde a meia-noite.

    No GTFS as horas podem passar das 24:00 (viagens que acabam depois da
    meia-noite), por isso não se usa datetime.
    """
    h, m, s = (int(x) for x in hora.strip().split(":"))
    return h * 60 + m + s / 60


def resumo(tabelas: dict[str, pd.DataFrame]) -> None:
    """Imprime um resumo para confirmar que os dados foram bem lidos."""
    em_falta = [n for n in OBRIGATORIOS if n not in tabelas]
    if em_falta:
        print("Ficheiros obrigatórios em falta:", ", ".join(em_falta))

    print("Ficheiros lidos:")
    for nome, df in tabelas.items():
        print(f"  {nome:<16} {len(df):>8} linhas")

    if "stops" in tabelas:
        print(f"\nParagens: {tabelas['stops']['stop_id'].nunique()}")
    if "routes" in tabelas:
        r = tabelas["routes"]
        col = "route_short_name" if "route_short_name" in r else "route_id"
        print(f"Linhas:   {r[col].nunique()}")
    if "trips" in tabelas:
        print(f"Viagens:  {tabelas['trips']['trip_id'].nunique()}")
    if "calendar" in tabelas:
        c = tabelas["calendar"]
        print(f"Período de serviço: {c['start_date'].min()} a {c['end_date'].max()}")
    if "stop_times" in tabelas:
        st = tabelas["stop_times"]
        minutos = st["departure_time"].dropna().map(hora_para_minutos)
        print(f"Primeira partida: {int(minutos.min() // 60):02d}:{int(minutos.min() % 60):02d}"
              f"  |  última: {int(minutos.max() // 60):02d}:{int(minutos.max() % 60):02d}")


if __name__ == "__main__":
    pasta = Path(sys.argv[1]) if len(sys.argv) > 1 else PASTA_GTFS
    tabelas = carregar_gtfs(pasta)
    if not tabelas:
        print(f"Não encontrei ficheiros GTFS em {pasta}.")
        print("Descarrega https://www.tub.pt/developer/gtfs/feed/tub.zip e descompacta para essa pasta.")
        sys.exit(1)
    resumo(tabelas)
