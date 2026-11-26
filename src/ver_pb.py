"""Ver o conteúdo de um ficheiro GTFS-Realtime (.pb ou .pb.gz).

Uso:
    python src/ver_pb.py FICHEIRO                 # resumo + primeiras linhas em tabela
    python src/ver_pb.py FICHEIRO --linhas 50     # mostrar mais linhas
    python src/ver_pb.py FICHEIRO --csv saida.csv # guardar a tabela completa em CSV
    python src/ver_pb.py FICHEIRO --bruto 2       # ver as 2 primeiras entidades em texto

O tipo de feed (trip_updates ou vehicle_positions) é detetado automaticamente.
"""
from __future__ import annotations

import argparse
import gzip
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from google.protobuf import text_format
try:
    from google.transit import gtfs_realtime_pb2
except ImportError as e:
    print(f"Erro ao importar o módulo GTFS-Realtime: {e}")
    exit(1)

LISBOA = ZoneInfo("Europe/Lisbon")
ESTADOS = {0: "A_CHEGAR", 1: "PARADO", 2: "EM_TRANSITO"}


def ler(caminho: Path) -> gtfs_realtime_pb2.FeedMessage:
    dados = caminho.read_bytes()
    if caminho.suffix == ".gz":
        dados = gzip.decompress(dados)
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(dados)
    return feed


def hora(ts: int) -> str | None:
    return datetime.fromtimestamp(ts, LISBOA).strftime("%H:%M:%S") if ts else None


def tabela_trip_updates(feed) -> pd.DataFrame:
    """Uma linha por previsão (viagem × paragem)."""
    linhas = []
    for e in feed.entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        for u in tu.stop_time_update:
            linhas.append({
                "trip_id": tu.trip.trip_id,
                "linha": tu.trip.route_id,
                "sentido": tu.trip.direction_id,
                "veiculo": tu.vehicle.id,
                "stop_sequence": u.stop_sequence,
                "stop_id": u.stop_id,
                "chegada_prevista": hora(u.arrival.time),
                "partida_prevista": hora(u.departure.time),
            })
    return pd.DataFrame(linhas)


def tabela_vehicle_positions(feed) -> pd.DataFrame:
    """Uma linha por autocarro."""
    linhas = []
    for e in feed.entity:
        if not e.HasField("vehicle"):
            continue
        v = e.vehicle
        linhas.append({
            "veiculo": v.vehicle.id,
            "trip_id": v.trip.trip_id,
            "linha": v.trip.route_id,
            "lat": round(v.position.latitude, 6),
            "lon": round(v.position.longitude, 6),
            "velocidade_kmh": round(v.position.speed * 3.6, 1) if v.position.HasField("speed") else None,
            "stop_sequence": v.current_stop_sequence,
            "stop_id": v.stop_id,
            "estado": ESTADOS.get(v.current_status, v.current_status),
            "hora": hora(v.timestamp),
        })
    return pd.DataFrame(linhas)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ficheiro", type=Path)
    p.add_argument("--linhas", type=int, default=20, help="linhas da tabela a mostrar")
    p.add_argument("--csv", type=Path, help="guardar a tabela completa em CSV")
    p.add_argument("--bruto", type=int, metavar="N", help="mostrar N entidades no formato original")
    args = p.parse_args()

    feed = ler(args.ficheiro)
    print(f"Ficheiro:  {args.ficheiro.name}")
    print(f"Gerado às: {hora(feed.header.timestamp)} (hora de Lisboa)")
    print(f"Entidades: {len(feed.entity)}\n")

    if args.bruto:
        for e in list(feed.entity)[:args.bruto]:
            print(text_format.MessageToString(e, as_utf8=True))
            print("-" * 60)
        return

    e0 = feed.entity[0] if feed.entity else None
    if e0 is not None and e0.HasField("trip_update"):
        df = tabela_trip_updates(feed)
        print(f"Tipo: trip_updates  |  {df['trip_id'].nunique()} viagens, {len(df)} previsões\n")
    else:
        df = tabela_vehicle_positions(feed)
        print(f"Tipo: vehicle_positions  |  {len(df)} autocarros\n")
        if not df.empty:
            print("Estados:", df["estado"].value_counts().to_dict(), "\n")

    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(df.head(args.linhas).to_string(index=False))

    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"\nTabela completa guardada em {args.csv} ({len(df)} linhas)")


if __name__ == "__main__":
    main()