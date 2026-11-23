"""Grafo dependente do tempo da rede dos TUB.

Cada estado é um par (paragem, hora em minutos). A partir de um estado há
dois tipos de ação:

  * Autocarro(trip, paragem_saida): apanhar a próxima passagem da viagem
    `trip` em `paragem` (depois da hora atual) e sair em `paragem_saida`;
  * Pe(paragem_destino): caminhar até uma paragem próxima.

A espera não é uma ação à parte: está incluída no tempo até o autocarro
passar.

Poda de ações dominadas: de cada linha, em cada sentido, só se
considera a PRÓXIMA viagem. Num modelo determinístico, apanhar um autocarro
mais tarde da mesma linha nunca chega antes do anterior, por isso essas
ações nunca podem melhorar a solução.

Uso:
    python src/grafo.py
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations

import pandas as pd

from gtfs import (UCP, carregar_gtfs, filtrar, haversine_km, minutos_para_hora,
                  procurar_paragem)

VELOCIDADE_PE_KMH = 5.0
RAIO_PE_KM = 0.4


@dataclass(frozen=True)
class Autocarro:
    trip_id: str
    linha: str
    paragem_saida: str

    def __str__(self) -> str:
        return f"Linha {self.linha} até {self.paragem_saida}"


@dataclass(frozen=True)
class Pe:
    paragem_destino: str
    minutos: float

    def __str__(self) -> str:
        return f"A pé até {self.paragem_destino} ({self.minutos:.0f} min)"


class Rede:
    """Rede de transportes dependente do tempo, construída a partir do GTFS filtrado."""

    def __init__(self, dados: dict[str, pd.DataFrame],
                 velocidade_pe_kmh: float = VELOCIDADE_PE_KMH,
                 raio_pe_km: float = RAIO_PE_KM):
        stops, st, trips, routes = (dados[k] for k in ("stops", "stop_times", "trips", "routes"))

        # Paragens: id -> (nome, lat, lon)
        self.paragens = {
            r.stop_id: (r.stop_name, r.stop_lat, r.stop_lon) for r in stops.itertuples()
        }

        # Nome curto da linha de cada viagem
        nome_linha = dict(zip(routes["route_id"],
                              routes.get("route_short_name", routes["route_id"])))
        self.linha_da_viagem = {
            r.trip_id: str(nome_linha.get(r.route_id, r.route_id)) for r in trips.itertuples()
        }

        # Sequência de cada viagem: trip -> [(paragem, chegada, partida), ...]
        self.percurso: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
        for r in st.itertuples():
            self.percurso[r.trip_id].append((r.stop_id, r.chegada, r.partida))

        # Partidas por paragem, ordenadas: paragem -> [(partida, trip, índice no percurso)]
        partidas = defaultdict(list)
        for trip, seq in self.percurso.items():
            for i, (p, _, dep) in enumerate(seq[:-1]):   # da última não se parte
                partidas[p].append((dep, trip, i))
        self.partidas = {p: sorted(v) for p, v in partidas.items()}
        self._horas = {p: [x[0] for x in v] for p, v in self.partidas.items()}

        # Ligações a pé entre paragens próximas
        self.vizinhos_pe: dict[str, list[tuple[str, float]]] = defaultdict(list)
        ids = list(self.paragens)
        for a, b in combinations(ids, 2):
            _, la1, lo1 = self.paragens[a]
            _, la2, lo2 = self.paragens[b]
            d = haversine_km(la1, lo1, la2, lo2)
            if d <= raio_pe_km:
                minutos = d / velocidade_pe_kmh * 60
                self.vizinhos_pe[a].append((b, minutos))
                self.vizinhos_pe[b].append((a, minutos))

        self.v_max_kmh = self._velocidade_maxima(velocidade_pe_kmh)

    # ------------------------------------------------------------------
    def _velocidade_maxima(self, velocidade_pe_kmh: float) -> float:
        """Maior velocidade média entre QUAISQUER duas paragens da mesma viagem.

        Usa todos os pares (i < j) e não só paragens consecutivas, porque uma
        ação de autocarro pode saltar várias paragens. Pares com tempo nulo
        (horários arredondados ao minuto) são ignorados.
        """
        v = velocidade_pe_kmh
        for seq in self.percurso.values():
            for i in range(len(seq)):
                p1, _, dep = seq[i]
                _, la1, lo1 = self.paragens[p1]
                for j in range(i + 1, len(seq)):
                    p2, arr, _ = seq[j]
                    dt = arr - dep
                    if dt <= 0:
                        continue
                    _, la2, lo2 = self.paragens[p2]
                    v = max(v, haversine_km(la1, lo1, la2, lo2) / (dt / 60))
        return v

    # ------------------------------------------------------------------
    def acoes(self, estado: tuple[str, float]) -> list:
        """Ações possíveis a partir de (paragem, hora)."""
        paragem, t = estado
        acoes = []

        # Autocarros: só a próxima viagem de cada (linha, sentido). O sentido
        # identifica-se pela paragem seguinte, o que não depende de a viagem
        # ter sido cortada pela janela horária.
        vistos = set()
        horas = self._horas.get(paragem, [])
        for dep, trip, i in self.partidas.get(paragem, [])[bisect_left(horas, t):]:
            sentido = (self.linha_da_viagem[trip], self.percurso[trip][i + 1][0])
            if sentido in vistos:
                continue
            vistos.add(sentido)
            for p_saida, _, _ in self.percurso[trip][i + 1:]:
                acoes.append(Autocarro(trip, self.linha_da_viagem[trip], p_saida))

        # A pé
        for destino, minutos in self.vizinhos_pe.get(paragem, []):
            acoes.append(Pe(destino, minutos))
        return acoes

    def resultado(self, estado: tuple[str, float], acao) -> tuple[str, float]:
        """Estado a que se chega ao aplicar a ação (modelo de transição)."""
        paragem, t = estado
        if isinstance(acao, Pe):
            return (acao.paragem_destino, t + acao.minutos)

        seq = self.percurso[acao.trip_id]
        idx = next(k for k, (p, _, dep) in enumerate(seq) if p == paragem and dep >= t)
        for p, chegada, _ in seq[idx + 1:]:
            if p == acao.paragem_saida:
                return (p, chegada)
        raise ValueError(f"{acao} não é válida a partir de {estado}")

    def heuristica(self, paragem: str, destino: str) -> float:
        """Minutos mínimos até ao destino: distância em linha reta / v_max."""
        _, la1, lo1 = self.paragens[paragem]
        _, la2, lo2 = self.paragens[destino]
        return haversine_km(la1, lo1, la2, lo2) / self.v_max_kmh * 60

    def nome(self, paragem: str) -> str:
        return self.paragens[paragem][0]

    # ------------------------------------------------------------------
    def resumo(self) -> None:
        n_pe = sum(len(v) for v in self.vizinhos_pe.values()) // 2
        n_bus = sum(len(seq) - 1 for seq in self.percurso.values())
        print(f"Paragens:            {len(self.paragens)}")
        print(f"Viagens:             {len(self.percurso)}")
        print(f"Troços de autocarro: {n_bus}")
        print(f"Ligações a pé:       {n_pe}")
        print(f"v_max:               {self.v_max_kmh:.1f} km/h")


# ----------------------------------------------------------------------
if __name__ == "__main__":
    tabelas = carregar_gtfs()
    if not tabelas:
        raise SystemExit("Sem dados GTFS em dados/gtfs/ — ver README.")

    dados = filtrar(tabelas, datetime.now().date())
    rede = Rede(dados)
    rede.resumo()

    # Exemplo: ações a partir da paragem mais próxima da UCP às 8h00
    perto = dados["stops"].nsmallest(1, "dist_centro_km").iloc[0]
    estado = (perto["stop_id"], 8 * 60)
    print(f"\nAções a partir de {perto['stop_name']} às {minutos_para_hora(estado[1])}:")
    acoes = rede.acoes(estado)
    for a in acoes[:15]:
        p, t = rede.resultado(estado, a)
        print(f"  {str(a):<45} -> {rede.nome(p)} às {minutos_para_hora(t)}")
    if len(acoes) > 15:
        print(f"  ... ({len(acoes)} ações no total)")
