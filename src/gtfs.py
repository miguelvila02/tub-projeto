"""Leitura, verificação e filtragem dos dados GTFS dos TUB.

Uso:
    python src/gtfs.py              # resumo de dados/gtfs/
    python src/gtfs.py caminho/     # resumo de outra pasta
"""
from __future__ import annotations

from datetime import date, datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
import sys

import pandas as pd

PASTA_GTFS = Path(__file__).resolve().parent.parent / "dados" / "gtfs"

OBRIGATORIOS = ["agency", "stops", "routes", "trips", "stop_times"]
OPCIONAIS = ["calendar", "calendar_dates", "shapes", "fare_attributes", "fare_rules"]

# Campus Camões da UCP Braga (GPS indicado no site da UCP: 41°33'16.13" N, 8°25'8.58" O)
UCP = (41.554481, -8.419050)

DIAS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ---------------------------------------------------------------------------
#  Leitura
# ---------------------------------------------------------------------------
def carregar_gtfs(pasta: Path = PASTA_GTFS) -> dict[str, pd.DataFrame]:
    """Lê os ficheiros GTFS da pasta para um dicionário de DataFrames.

    Tudo é lido como texto, para não perder zeros à esquerda nos
    identificadores. As colunas numéricas convertem-se a seguir.
    """
    pasta = Path(pasta)
    tabelas = {}
    for nome in OBRIGATORIOS + OPCIONAIS:
        ficheiro = pasta / f"{nome}.txt"
        if ficheiro.exists():
            df = pd.read_csv(ficheiro, dtype=str, encoding="utf-8-sig")
            df.columns = df.columns.str.strip()
            tabelas[nome] = df

    if "stops" in tabelas:
        for col in ("stop_lat", "stop_lon"):
            tabelas["stops"][col] = tabelas["stops"][col].astype(float)
    if "stop_times" in tabelas:
        st = tabelas["stop_times"]
        st["stop_sequence"] = st["stop_sequence"].astype(int)
        st["chegada"] = st["arrival_time"].map(hora_para_minutos)
        st["partida"] = st["departure_time"].map(hora_para_minutos)
        # Algumas paragens intermédias podem não ter hora (interpoladas)
        st["chegada"] = st["chegada"].fillna(st["partida"])
        st["partida"] = st["partida"].fillna(st["chegada"])
    return tabelas


# ---------------------------------------------------------------------------
#  Utilitários
# ---------------------------------------------------------------------------
def hora_para_minutos(hora) -> float:
    """'HH:MM:SS' -> minutos desde a meia-noite (aceita horas >= 24)."""
    if not isinstance(hora, str) or not hora.strip():
        return float("nan")
    h, m, s = (int(x) for x in hora.strip().split(":"))
    return h * 60 + m + s / 60


def minutos_para_hora(minutos: float) -> str:
    """Minutos desde a meia-noite -> 'HH:MM'."""
    minutos = round(minutos)
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distância em linha reta (km) entre dois pontos na superfície da Terra."""
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


# ---------------------------------------------------------------------------
#  Filtragem
# ---------------------------------------------------------------------------
def servicos_ativos(tabelas: dict[str, pd.DataFrame], dia: date) -> set[str]:
    """service_id em funcionamento num dado dia.

    Combina o calendar.txt (dias da semana + período de validade) com as
    exceções do calendar_dates.txt (1 = acrescentar, 2 = retirar).
    """
    ativos: set[str] = set()
    ymd = dia.strftime("%Y%m%d")

    if "calendar" in tabelas:
        cal = tabelas["calendar"]
        coluna_dia = DIAS[dia.weekday()]
        sel = (cal[coluna_dia] == "1") & (cal["start_date"] <= ymd) & (cal["end_date"] >= ymd)
        ativos |= set(cal.loc[sel, "service_id"])

    if "calendar_dates" in tabelas:
        cd = tabelas["calendar_dates"]
        cd = cd[cd["date"] == ymd]
        ativos |= set(cd.loc[cd["exception_type"] == "1", "service_id"])
        ativos -= set(cd.loc[cd["exception_type"] == "2", "service_id"])

    return ativos


def filtrar(
    tabelas: dict[str, pd.DataFrame],
    dia: date,
    hora_inicio: str = "07:00",
    hora_fim: str = "10:00",
    centro: tuple[float, float] = UCP,
    raio_km: float | None = 3.0,
) -> dict[str, pd.DataFrame]:
    """Reduz os dados a um dia, uma janela horária e uma zona.

    - dia: só as viagens cujo serviço funciona nesse dia;
    - janela: só as passagens entre hora_inicio e hora_fim;
    - zona: só as paragens a menos de raio_km do centro (None = sem limite).

    Devolve {'stops', 'stop_times', 'trips', 'routes'} já filtrados.
    """
    ini = hora_para_minutos(hora_inicio + ":00")
    fim = hora_para_minutos(hora_fim + ":00")

    stops = tabelas["stops"].copy()
    stops["dist_centro_km"] = [
        haversine_km(centro[0], centro[1], la, lo)
        for la, lo in zip(stops["stop_lat"], stops["stop_lon"])
    ]
    if raio_km is not None:
        stops = stops[stops["dist_centro_km"] <= raio_km]

    servicos = servicos_ativos(tabelas, dia)
    trips = tabelas["trips"][tabelas["trips"]["service_id"].isin(servicos)]

    st = tabelas["stop_times"]
    st = st[
        st["trip_id"].isin(trips["trip_id"])
        & st["stop_id"].isin(stops["stop_id"])
        & (st["partida"] >= ini)
        & (st["chegada"] <= fim)
    ].sort_values(["trip_id", "stop_sequence"])

    # Uma viagem só serve se passar em pelo menos 2 paragens da zona
    n_por_viagem = st.groupby("trip_id")["stop_id"].transform("size")
    st = st[n_por_viagem >= 2]

    trips = trips[trips["trip_id"].isin(st["trip_id"])]
    stops = stops[stops["stop_id"].isin(st["stop_id"])]
    routes = tabelas["routes"][tabelas["routes"]["route_id"].isin(trips["route_id"])]

    return {"stops": stops, "stop_times": st, "trips": trips, "routes": routes}


def procurar_paragem(stops: pd.DataFrame, texto: str) -> pd.DataFrame:
    """Paragens cujo nome contém o texto (sem distinguir maiúsculas)."""
    return stops[stops["stop_name"].str.contains(texto, case=False, na=False)]


# ---------------------------------------------------------------------------
#  Resumo
# ---------------------------------------------------------------------------
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
        p = tabelas["stop_times"]["partida"].dropna()
        print(f"Primeira partida: {minutos_para_hora(p.min())}  |  última: {minutos_para_hora(p.max())}")


if __name__ == "__main__":
    pasta = Path(sys.argv[1]) if len(sys.argv) > 1 else PASTA_GTFS
    tabelas = carregar_gtfs(pasta)
    if not tabelas:
        print(f"Não encontrei ficheiros GTFS em {pasta}.")
        print("Descarrega https://www.tub.pt/developer/gtfs/feed/tub.zip e descompacta para essa pasta.")
        sys.exit(1)
    resumo(tabelas)

    hoje = datetime.now().date()
    f = filtrar(tabelas, hoje)
    print(f"\nFiltro de hoje ({hoje}, 07:00-10:00, 3 km da UCP):")
    print(f"  paragens {len(f['stops'])}  |  viagens {len(f['trips'])}  |  passagens {len(f['stop_times'])}")
    perto = f["stops"].nsmallest(5, "dist_centro_km")[["stop_id", "stop_name", "dist_centro_km"]]
    print("\nParagens mais próximas da UCP:")
    print(perto.to_string(index=False))
