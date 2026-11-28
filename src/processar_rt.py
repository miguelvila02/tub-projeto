"""Transforma os retratos do feed GTFS-Realtime em passagens com hora real e atraso.

Entrada:  dados/gtfs_rt/brutos/AAAA-MM-DD/{trip_updates,vehicle_positions}_HHMMSS.pb.gz
          dados/gtfs/ (horário)       dados/meteo/meteo_braga.csv (opcional)
Saída:    dados/gtfs_rt/processados/
            passagens.csv      1 linha por (dia, viagem, paragem): horário, hora real, atraso
            tempos_trocos.csv  tempo real entre paragens consecutivas, por faixa horária
            previsoes.csv      todas as previsões vistas (grande; para avaliar as previsões dos TUB)

MÉTODO A (principal) - pelas previsões (trip_updates)
    O feed só lista as paragens que faltam. Quando o autocarro passa numa
    paragem, ela desaparece do feed. A hora real é a ÚLTIMA previsão de chegada
    vista para essa paragem (feita, no máximo, um intervalo de recolha antes).
    Uma passagem só é aceite se houver prova de que aconteceu: a viagem continua
    no feed sem essa paragem, ou a última previsão era para menos de 2 min.

MÉTODO B (validação) - pelo GPS (vehicle_positions)
    Quando o veículo aparece PARADO (STOPPED_AT) numa paragem, essa hora é uma
    observação direta da passagem. Só cobre algumas paragens, mas serve para
    medir o erro do método A.

Uso:
    python src/processar_rt.py                      # todos os dias disponíveis
    python src/processar_rt.py --dias 2026-11-28    # só alguns dias
    python src/processar_rt.py --sem-previsoes      # não escreve previsoes.csv
"""
from __future__ import annotations

import argparse
import gzip
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from google.transit import gtfs_realtime_pb2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gtfs import PASTA_GTFS, carregar_gtfs  # noqa: E402

LISBOA = ZoneInfo("Europe/Lisbon")
RAIZ = Path(__file__).resolve().parent.parent
BRUTOS = RAIZ / "dados" / "gtfs_rt" / "brutos"
SAIDA = RAIZ / "dados" / "gtfs_rt" / "processados"
METEO = RAIZ / "dados" / "meteo" / "meteo_braga.csv"

STOPPED_AT = 1
HORIZONTE_MAX_S = 120      # última previsão aceite sem outra prova: no máximo 2 min no futuro

# Critérios de qualidade de cada passagem (coluna "qualidade")
HORIZONTE_BOM_S = (-180, 120)   # a última previsão foi feita perto da passagem
ADIANTAMENTO_SUSPEITO_MIN = -8  # adiantamentos maiores: provável viagem trocada no feed

# Feriados nacionais (Portugal) no período do projeto
FERIADOS = {date(2026, 12, 1), date(2026, 12, 8), date(2026, 12, 25), date(2027, 1, 1)}
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def tipo_dia(d: date) -> str:
    if d in FERIADOS or d.weekday() == 6:
        return "domingo_feriado"
    if d.weekday() == 5:
        return "sabado"
    return "util"


def ler(f: Path) -> gtfs_realtime_pb2.FeedMessage:
    m = gtfs_realtime_pb2.FeedMessage()
    m.ParseFromString(gzip.open(f).read())
    return m


# ---------------------------------------------------------------------------
def processar_dia(pasta: Path, guardar_previsoes: bool):
    """Lê todos os retratos de um dia. Devolve (passagens_A, gps_B, previsoes)."""
    tus = sorted(pasta.glob("trip_updates_*.pb.gz"))
    vps = sorted(pasta.glob("vehicle_positions_*.pb.gz"))

    ultima = {}                     # (start_date, trip, seq) -> (t_retrato, stop_id, chegada, linha)
    viagem_vista = defaultdict(list)  # (start_date, trip) -> [t_retrato, ...]
    previsoes = []
    tempos_retrato = []

    for f in tus:
        m = ler(f)
        t = m.header.timestamp
        tempos_retrato.append(t)
        for e in m.entity:
            if not e.HasField("trip_update"):
                continue
            tu = e.trip_update
            chave_v = (tu.trip.start_date, tu.trip.trip_id)
            viagem_vista[chave_v].append(t)
            for u in tu.stop_time_update:
                chegada = u.arrival.time or u.departure.time
                if not chegada:
                    continue
                ultima[chave_v + (u.stop_sequence,)] = (t, u.stop_id, chegada, tu.trip.route_id)
                if guardar_previsoes:
                    previsoes.append((tu.trip.start_date, tu.trip.trip_id, u.stop_sequence,
                                      u.stop_id, t, chegada))

    if not tempos_retrato:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    ultimo_retrato = max(tempos_retrato)

    # Método A: aceitar só passagens com prova
    linhas_a = []
    for (sd, trip, seq), (t, stop, chegada, linha) in ultima.items():
        if t == ultimo_retrato:
            continue                                  # recolha acabou antes da passagem
        viagem_continuou = any(x > t for x in viagem_vista[(sd, trip)])
        if viagem_continuou or chegada - t <= HORIZONTE_MAX_S:
            linhas_a.append((sd, trip, linha, seq, stop, chegada, t, chegada - t))
    passagens = pd.DataFrame(linhas_a, columns=[
        "start_date", "trip_id", "linha", "stop_sequence", "stop_id",
        "ts_real", "ts_ultima_previsao", "horizonte_s"])

    # Método B: primeira vez que o veículo aparece PARADO em cada paragem
    gps = {}
    for f in vps:
        m = ler(f)
        for e in m.entity:
            if not e.HasField("vehicle"):
                continue
            v = e.vehicle
            if v.current_status != STOPPED_AT or not v.timestamp:
                continue
            chave = (v.trip.start_date, v.trip.trip_id, v.current_stop_sequence)
            if chave not in gps or v.timestamp < gps[chave]:
                gps[chave] = v.timestamp
    gps = pd.DataFrame([(sd, tr, sq, ts) for (sd, tr, sq), ts in gps.items()],
                       columns=["start_date", "trip_id", "stop_sequence", "ts_gps"])

    prev = pd.DataFrame(previsoes, columns=["start_date", "trip_id", "stop_sequence", "stop_id",
                                            "ts_retrato", "ts_previsto"]) if guardar_previsoes else pd.DataFrame()
    return passagens, gps, prev


def para_lisboa(ts: pd.Series) -> pd.Series:
    return pd.to_datetime(ts, unit="s", utc=True).dt.tz_convert(LISBOA).dt.tz_localize(None)


def juntar_horario(p: pd.DataFrame, stop_times: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta a hora do horário (GTFS) e calcula o atraso."""
    h = stop_times[["trip_id", "stop_sequence", "stop_id", "chegada"]].rename(
        columns={"stop_id": "stop_id_gtfs", "chegada": "min_horario"})
    p = p.merge(h, on=["trip_id", "stop_sequence"], how="left")
    dia = pd.to_datetime(p["start_date"], format="%Y%m%d")
    p["hora_horario"] = dia + pd.to_timedelta(p["min_horario"], unit="min")
    p["hora_real"] = para_lisboa(p["ts_real"])
    p["atraso_min"] = (p["hora_real"] - p["hora_horario"]).dt.total_seconds() / 60
    p["stop_id_coincide"] = p["stop_id"] == p["stop_id_gtfs"]
    return p


def tempos_trocos(p: pd.DataFrame) -> pd.DataFrame:
    """Tempo real e do horário entre paragens consecutivas da mesma viagem."""
    p = p.sort_values(["start_date", "trip_id", "stop_sequence"])
    seguinte = p.groupby(["start_date", "trip_id"]).shift(-1)
    t = pd.DataFrame({
        "data": p["data"], "tipo_dia": p["tipo_dia"], "linha": p["linha"],
        "de_stop": p["stop_id"], "para_stop": seguinte["stop_id"],
        "de_seq": p["stop_sequence"], "para_seq": seguinte["stop_sequence"],
        "hora": p["hora_real"],
        "real_min": (seguinte["hora_real"] - p["hora_real"]).dt.total_seconds() / 60,
        "horario_min": (seguinte["hora_horario"] - p["hora_horario"]).dt.total_seconds() / 60,
    }).dropna(subset=["para_stop"])
    t = t[t["para_seq"] == t["de_seq"] + 1]          # só paragens mesmo consecutivas
    t["faixa"] = t["hora"].dt.floor("30min").dt.strftime("%H:%M")
    agg = (t.groupby(["linha", "de_stop", "para_stop", "tipo_dia", "faixa"])
             .agg(n=("real_min", "size"),
                  mediana_min=("real_min", "median"),
                  p90_min=("real_min", lambda s: s.quantile(0.9)),
                  media_min=("real_min", "mean"),
                  horario_min=("horario_min", "median"))
             .reset_index())
    return agg.round(2)


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brutos", type=Path, default=BRUTOS)
    ap.add_argument("--gtfs", type=Path, default=PASTA_GTFS)
    ap.add_argument("--saida", type=Path, default=SAIDA)
    ap.add_argument("--meteo", type=Path, default=METEO)
    ap.add_argument("--dias", nargs="*", help="AAAA-MM-DD (por omissão, todos)")
    ap.add_argument("--sem-previsoes", action="store_true", help="não escrever previsoes.csv")
    args = ap.parse_args()

    pastas = sorted(d for d in args.brutos.glob("20??-??-??") if d.is_dir())
    if args.dias:
        pastas = [d for d in pastas if d.name in args.dias]
    if not pastas:
        print(f"Sem dias em {args.brutos}")
        return 1

    st = carregar_gtfs(args.gtfs)["stop_times"]
    todas_p, todas_g, todas_prev = [], [], []
    for d in pastas:
        p, g, prev = processar_dia(d, not args.sem_previsoes)
        print(f"{d.name}: {len(p):6d} passagens (método A), {len(g):5d} paragens com GPS (método B)")
        todas_p.append(p); todas_g.append(g); todas_prev.append(prev)

    p = pd.concat(todas_p, ignore_index=True)
    g = pd.concat(todas_g, ignore_index=True)
    if p.empty:
        print("Nenhuma passagem encontrada.")
        return 1
    # A mesma passagem pode aparecer em dois dias de recolha (viagens perto da meia-noite)
    p = p.sort_values("ts_ultima_previsao").drop_duplicates(
        ["start_date", "trip_id", "stop_sequence"], keep="last")

    p = juntar_horario(p, st)
    p["data"] = pd.to_datetime(p["start_date"], format="%Y%m%d").dt.date
    p["tipo_dia"] = p["data"].map(tipo_dia)
    p["dia_semana"] = p["data"].map(lambda d: DIAS_SEMANA[d.weekday()])
    p["faixa"] = p["hora_real"].dt.floor("30min").dt.strftime("%H:%M")

    # Validação com o GPS
    p = p.merge(g, on=["start_date", "trip_id", "stop_sequence"], how="left")
    p["hora_gps"] = para_lisboa(p["ts_gps"])
    p["dif_gps_s"] = p["ts_real"] - p["ts_gps"]

    # Meteorologia (opcional)
    if args.meteo.exists():
        met = pd.read_csv(args.meteo, parse_dates=["hora"])
        p["hora_cheia"] = p["hora_real"].dt.floor("h")
        p = p.merge(met[["hora", "precipitacao_mm", "temperatura_c"]],
                    left_on="hora_cheia", right_on="hora", how="left").drop(columns=["hora", "hora_cheia"])

    # Qualidade: "boa" | "imprecisa" (última previsão longe da passagem) | "suspeita" (viagem trocada?)
    lo, hi = HORIZONTE_BOM_S
    adiant_viagem = p.groupby(["start_date", "trip_id"])["atraso_min"].transform("median")
    p["qualidade"] = "boa"
    p.loc[(p["horizonte_s"] < lo) | (p["horizonte_s"] > hi), "qualidade"] = "imprecisa"
    p.loc[adiant_viagem < ADIANTAMENTO_SUSPEITO_MIN, "qualidade"] = "suspeita"

    colunas = ["data", "tipo_dia", "dia_semana", "faixa", "linha", "trip_id", "stop_sequence", "stop_id",
               "hora_horario", "hora_real", "atraso_min", "qualidade", "horizonte_s", "hora_gps", "dif_gps_s"]
    colunas += [c for c in ("precipitacao_mm", "temperatura_c") if c in p.columns]
    saida = p[colunas].sort_values(["data", "trip_id", "stop_sequence"])
    saida["atraso_min"] = saida["atraso_min"].round(2)

    args.saida.mkdir(parents=True, exist_ok=True)
    saida.to_csv(args.saida / "passagens.csv", index=False)
    tempos_trocos(p[p["qualidade"] == "boa"]).to_csv(args.saida / "tempos_trocos.csv", index=False)
    if not args.sem_previsoes:
        prev = pd.concat(todas_prev, ignore_index=True)
        prev.to_csv(args.saida / "previsoes.csv", index=False)

    # ----------------------------------------------------------------- resumo
    sem_horario = p["min_horario"].isna().mean()
    stop_ok = p.loc[p["min_horario"].notna(), "stop_id_coincide"].mean()
    v = p.dropna(subset=["dif_gps_s"])
    print(f"\nPassagens: {len(saida)}  |  viagens: {p['trip_id'].nunique()}  |  linhas: {p['linha'].nunique()}")
    print(f"Sem correspondência no horário: {sem_horario:.1%}  |  stop_id igual ao GTFS: {stop_ok:.1%}")
    print("Qualidade:", saida["qualidade"].value_counts(normalize=True).round(3).to_dict())
    for nome, sub in (("todas", v), ("só 'boa'", v[v["qualidade"] == "boa"])):
        if len(sub):
            print(f"Validação A vs GPS, {nome} ({len(sub)} passagens): diferença mediana "
                  f"{sub['dif_gps_s'].median():+.0f} s | |dif| <= 60 s: {(sub['dif_gps_s'].abs() <= 60).mean():.0%}"
                  f" | <= 120 s: {(sub['dif_gps_s'].abs() <= 120).mean():.0%}")
    boas = saida[saida["qualidade"] == "boa"]
    print("\nAtraso (min) das passagens de qualidade 'boa', por tipo de dia:")
    print(boas.groupby("tipo_dia")["atraso_min"].describe(percentiles=[.1, .5, .9]).round(1).to_string())
    print(f"\nFicheiros em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())