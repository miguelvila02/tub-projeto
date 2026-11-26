"""Recolha periódica do feed GTFS-Realtime dos TUB.

Descarrega os feeds `trip_updates` e `vehicle_positions` em intervalos
regulares, dentro de janelas horárias (manhã e fim de tarde), e guarda cada resposta comprimida:

    dados/gtfs_rt/brutos/AAAA-MM-DD/trip_updates_HHMMSS.pb.gz
    dados/gtfs_rt/brutos/AAAA-MM-DD/vehicle_positions_HHMMSS.pb.gz

Se o conteúdo de um feed não mudou desde o pedido anterior, não se guarda
outra cópia (poupa espaço). Todas as horas são de Lisboa, mesmo que o
computador esteja noutro fuso (por exemplo, num servidor do GitHub).

Uso:
    python src/recolha_rt.py                  # dias úteis, 06:30-10:30 e 16:30-19:30
    python src/recolha_rt.py --uma-vez        # um pedido a cada feed e sai (teste)
    python src/recolha_rt.py --sempre         # ignora as janelas horárias
    python src/recolha_rt.py --sair-no-fim    # recolhe a janela atual (ou a próxima, se
                                              # abrir dentro de 60 min) e sai
    python src/recolha_rt.py --janelas 07:00-09:30,17:00-19:00 --intervalo 60

Os TUB pediram uma frequência de pedidos moderada: não baixar o intervalo
abaixo de 30 s.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import logging
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from google.transit import gtfs_realtime_pb2
except ImportError:  # a recolha funciona sem isto; só não valida o conteúdo
    gtfs_realtime_pb2 = None

LISBOA = ZoneInfo("Europe/Lisbon")
RAIZ = Path(__file__).resolve().parent.parent
PASTA_BRUTOS = RAIZ / "dados" / "gtfs_rt" / "brutos"

FEEDS = {
    "trip_updates": "https://mobibus-gateway.fleetaware.pt/gtfs-rt/feed/trip_updates.pb",
    "vehicle_positions": "https://mobibus-gateway.fleetaware.pt/gtfs-rt/feed/vehicle_positions.pb",
}

USER_AGENT = "tub-projeto/1.0 (projeto academico, LCDA - UCP Braga)"
TIMEOUT_S = 20
TENTATIVAS = 3
INTERVALO_MINIMO_S = 30

log = logging.getLogger("recolha_rt")
_parar = False


# ---------------------------------------------------------------------------
def _pedir_paragem(signum, frame):
    global _parar
    _parar = True
    log.info("Sinal recebido; a terminar depois do pedido atual.")


DIAS_PT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def agora() -> datetime:
    return datetime.now(LISBOA)


def hora(texto: str) -> dtime:
    h, m = (int(x) for x in texto.split(":"))
    return dtime(h, m)


def descarregar(url: str) -> bytes:
    """GET com algumas tentativas e espera crescente entre elas."""
    pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ultimo_erro = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            with urllib.request.urlopen(pedido, timeout=TIMEOUT_S) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as erro:
            ultimo_erro = erro
            if tentativa < TENTATIVAS:
                time.sleep(2 * tentativa)
    raise RuntimeError(f"falhou após {TENTATIVAS} tentativas: {ultimo_erro}")


def descrever(conteudo: bytes) -> str:
    """Resumo do feed (n.º de entidades e idade), se as bindings existirem."""
    if gtfs_realtime_pb2 is None:
        return f"{len(conteudo) / 1024:.0f} KB"
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(conteudo)  # lança exceção se o conteúdo for inválido
    idade = ""
    if feed.header.timestamp:
        idade = f", gerado há {time.time() - feed.header.timestamp:.0f} s"
    return f"{len(feed.entity)} entidades, {len(conteudo) / 1024:.0f} KB{idade}"


class Recolhedor:
    def __init__(self, pasta: Path, feeds: dict[str, str]):
        self.pasta = pasta
        self.feeds = feeds
        self.ultimo_hash: dict[str, str] = {}
        self.guardados = 0
        self.repetidos = 0
        self.erros = 0

    def recolher(self) -> None:
        """Um pedido a cada feed."""
        instante = agora()
        pasta_dia = self.pasta / instante.strftime("%Y-%m-%d")
        pasta_dia.mkdir(parents=True, exist_ok=True)

        for nome, url in self.feeds.items():
            try:
                conteudo = descarregar(url)
            except RuntimeError as erro:
                self.erros += 1
                log.warning("%-17s ERRO %s", nome, erro)
                continue

            h = hashlib.sha1(conteudo).hexdigest()
            if self.ultimo_hash.get(nome) == h:
                self.repetidos += 1
                log.info("%-17s sem alterações", nome)
                continue
            self.ultimo_hash[nome] = h

            try:
                resumo = descrever(conteudo)
            except Exception as erro:  # conteúdo inválido: guarda na mesma, para análise
                resumo = f"CONTEÚDO INVÁLIDO ({erro})"
                self.erros += 1

            destino = pasta_dia / f"{nome}_{instante.strftime('%H%M%S')}.pb.gz"
            with gzip.open(destino, "wb") as f:
                f.write(conteudo)
            self.guardados += 1
            log.info("%-17s %s -> %s", nome, resumo, destino.name)

    def balanco(self) -> str:
        return (f"{self.guardados} guardados, {self.repetidos} sem alterações, "
                f"{self.erros} erros")


# ---------------------------------------------------------------------------
def ler_janelas(texto: str) -> list[tuple[dtime, dtime]]:
    """'06:30-10:30,16:30-19:30' -> [(06:30, 10:30), (16:30, 19:30)]"""
    janelas = []
    for parte in texto.split(","):
        ini, fim = (hora(x.strip()) for x in parte.split("-"))
        if fim <= ini:
            raise ValueError(f"janela inválida: {parte}")
        janelas.append((ini, fim))
    return sorted(janelas)


def janela_atual(t: datetime, janelas, fins_de_semana: bool):
    """A janela (início, fim) em que `t` está, ou None."""
    if not fins_de_semana and t.weekday() >= 5:
        return None
    for ini, fim in janelas:
        if ini <= t.time() < fim:
            return ini, fim
    return None


def proximo_inicio(t: datetime, janelas, fins_de_semana: bool) -> datetime:
    """Próximo instante em que alguma janela abre."""
    dia = t.replace(second=0, microsecond=0)
    for _ in range(8):
        if fins_de_semana or dia.weekday() < 5:
            for ini, _fim in janelas:
                candidato = dia.replace(hour=ini.hour, minute=ini.minute)
                if candidato > t:
                    return candidato
        dia = (dia + timedelta(days=1)).replace(hour=0, minute=0)
    raise RuntimeError("nenhuma janela nos próximos 7 dias")


def dormir_ate(alvo: datetime) -> None:
    """Dorme até `alvo`, acordando a cada segundo para poder ser interrompido."""
    while not _parar:
        falta = (alvo - agora()).total_seconds()
        if falta <= 0:
            return
        time.sleep(min(falta, 1))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--janelas", default="06:30-10:30,16:30-19:30",
                   help="janelas de recolha, hora de Lisboa (ex.: 06:30-10:30,16:30-19:30)")
    p.add_argument("--intervalo", type=int, default=60, help="segundos entre pedidos (mín. 30)")
    p.add_argument("--fins-de-semana", action="store_true", help="recolher também ao sábado e domingo")
    p.add_argument("--sempre", action="store_true", help="ignorar a janela horária")
    p.add_argument("--uma-vez", action="store_true", help="um único pedido a cada feed (teste)")
    p.add_argument("--sair-no-fim", action="store_true",
                   help="terminar quando a janela atual acabar (ou se a próxima estiver longe)")
    p.add_argument("--espera-max", type=int, default=60,
                   help="com --sair-no-fim: minutos máximos à espera que uma janela abra")
    p.add_argument("--pasta", type=Path, default=PASTA_BRUTOS, help="onde guardar os ficheiros")
    p.add_argument("--url-trip-updates", default=FEEDS["trip_updates"])
    p.add_argument("--url-vehicle-positions", default=FEEDS["vehicle_positions"])
    args = p.parse_args()

    if args.intervalo < INTERVALO_MINIMO_S:
        p.error(f"--intervalo tem de ser pelo menos {INTERVALO_MINIMO_S} s (pedido dos TUB)")

    args.pasta.mkdir(parents=True, exist_ok=True)
    ficheiro_log = args.pasta / f"recolha_{agora():%Y-%m-%d_%H%M}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(ficheiro_log, encoding="utf-8")],
    )
    logging.Formatter.converter = staticmethod(
        lambda segundos: datetime.fromtimestamp(segundos, LISBOA).timetuple())

    signal.signal(signal.SIGINT, _pedir_paragem)
    signal.signal(signal.SIGTERM, _pedir_paragem)

    if gtfs_realtime_pb2 is None:
        log.info("Aviso: gtfs-realtime-bindings não instalado; os feeds são guardados sem validação.")

    feeds = {"trip_updates": args.url_trip_updates,
             "vehicle_positions": args.url_vehicle_positions}
    rec = Recolhedor(args.pasta, feeds)
    try:
        janelas = ler_janelas(args.janelas)
    except ValueError as erro:
        p.error(str(erro))

    if args.uma_vez:
        rec.recolher()
        log.info("Teste concluído: %s", rec.balanco())
        return 0 if rec.erros == 0 else 1

    descricao = "sempre" if args.sempre else args.janelas
    log.info("Recolha iniciada (janelas %s, intervalo %d s). Ctrl+C para parar.", descricao, args.intervalo)
    ja_recolheu = False

    while not _parar:
        t = agora()
        janela = None if args.sempre else janela_atual(t, janelas, args.fins_de_semana)
        if args.sempre or janela:
            tick = time.monotonic()
            rec.recolher()
            ja_recolheu = True
            # Mantém o ritmo certo, descontando o tempo do pedido
            alvo = agora() + timedelta(seconds=max(0.0, args.intervalo - (time.monotonic() - tick)))
            if janela:
                fim_janela = t.replace(hour=janela[1].hour, minute=janela[1].minute, second=0, microsecond=0)
                alvo = min(alvo, fim_janela)
            dormir_ate(alvo)
            continue

        # Fora de qualquer janela
        seguinte = proximo_inicio(t, janelas, args.fins_de_semana)
        if args.sair_no_fim:
            if ja_recolheu:
                log.info("Janela terminada.")
                break
            if (seguinte - t) > timedelta(minutes=args.espera_max):
                log.info("Próxima janela só às %s; nada a fazer agora.", f"{seguinte:%H:%M}")
                break
        log.info("Fora da janela. Próxima recolha: %s", f"{DIAS_PT[seguinte.weekday()]} {seguinte:%d/%m %H:%M}")
        dormir_ate(seguinte)

    log.info("Recolha terminada: %s", rec.balanco())
    return 0


if __name__ == "__main__":
    sys.exit(main())