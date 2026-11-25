# Chegar a horas em Braga

Projeto opcional de Inteligência Artificial (LCDA, UCP Braga, 2026/27).
Procura informada e cadeias de Markov na rede dos TUB (Transportes Urbanos de Braga).

**Pergunta de partida:** a que horas devo sair, e por que rota, para chegar à UCP
antes das 9h00 com 95 % de certeza?

## Estrutura

```
tub-projeto/
├── dados/
│   ├── gtfs/        # ficheiros GTFS dos TUB (descompactados)
│   └── atrasos/     # registo de atrasos recolhidos no terreno
├── src/
│   ├── gtfs.py      # ler e filtrar os dados GTFS
│   ├── grafo.py     # construir o grafo (paragem, hora)
│   ├── recolha_rt.py # recolha periódica do feed GTFS-Realtime
│   ├── procura.py   # formulação do problema + algoritmos de procura
│   ├── markov.py    # cadeia de Markov dos atrasos
│   └── simulacao.py # Monte Carlo
├── notebooks/       # exploração e gráficos
├── figuras/         # figuras para o relatório
└── relatorio/       # LaTeX do relatório
```

## Instalação

Com conda:

```bash
conda env create -f environment.yml
conda activate tub-projeto

# aima-python (implementação de referência do livro)
git clone https://github.com/aimacode/aima-python.git lib/aima-python
```

Para atualizar o ambiente depois de mudar o `environment.yml`:

```bash
conda env update -f environment.yml --prune
```

(Alternativa sem conda: `pip install -r requirements.txt`.)

## Dados

1. Descarregar o GTFS: <https://www.tub.pt/developer/gtfs/feed/tub.zip>
   (alternativa: <https://dados.gov.pt/pt/datasets/gtfs-transportes-urbanos-de-braga/>)
2. Descompactar para `dados/gtfs/`.
3. Verificar:

```bash
python src/gtfs.py
```

## Recolha do tempo real (GTFS-Realtime)

Os TUB disponibilizam dois feeds, que `src/recolha_rt.py` descarrega a cada
minuto, nos dias úteis entre as 06:30 e as 10:30 (hora de Lisboa):

- `trip_updates`: previsões de chegada e atrasos;
- `vehicle_positions`: posição GPS dos veículos.

Os ficheiros ficam em `dados/gtfs_rt/brutos/AAAA-MM-DD/`, comprimidos. Se um
feed não mudou desde o pedido anterior, não se guarda outra cópia.

**Os TUB pediram uma frequência moderada de pedidos: não usar intervalos
abaixo de 60 s sem necessidade (o script recusa menos de 30 s).**

### Opção A: automática, no GitHub (recomendada)

O workflow `.github/workflows/recolha.yml` corre sozinho nos dias úteis de manhã,
nos servidores do GitHub, sem ser preciso ter o computador ligado.

1. Fazer push do projeto (o repositório tem de ser **público**: nos privados os
   minutos gratuitos não chegam).
2. Testar: separador **Actions** → *Recolha GTFS-RT* → **Run workflow**
   (com "Só um pedido" marcado). No fim, a execução tem um artefacto com 2 ficheiros.
3. A partir daí corre sozinho. Para trazer os dados para o computador:

```bash
bash scripts/descarregar_dados.sh
```

Os artefactos ficam guardados 90 dias no GitHub.

### Opção B: no computador

```bash
python src/recolha_rt.py --uma-vez     # teste rápido
python src/recolha_rt.py               # fica a correr; recolhe nos dias úteis 06:30-10:30
```

O computador tem de estar ligado e sem suspender durante a janela.

## Registo de atrasos (opcional)

Opcional: o tempo real valida-se cruzando os dois feeds. Se calhar, anotar
algumas passagens em `dados/atrasos/registo_atrasos.csv`, uma linha por paragem observada.
Anotar 2 a 4 paragens por viagem e usar o mesmo `id_viagem` em todas as linhas da mesma viagem.

| coluna         | exemplo     | notas                                   |
|----------------|-------------|-----------------------------------------|
| id_viagem      | 1           | número sequencial, igual na mesma viagem |
| data           | 2026-11-19  |                                          |
| dia_semana     | qui         |                                          |
| linha          | 43          |                                          |
| sentido        | UCP         | destino indicado no autocarro            |
| ordem_paragem  | 1           | 1.ª, 2.ª, ... paragem observada          |
| paragem        | Av. Liberdade |                                        |
| hora_prevista  | 08:12       | segundo o horário                        |
| hora_real      | 08:15       | quando o autocarro chegou de facto       |
| observacoes    | chuva       | opcional                                 |

## Fases

- [x] Fase 0 — Proposta
- [ ] Fase 1 — Preparar o ambiente
- [ ] Fase 2 — Recolha de atrasos (em paralelo)
- [ ] Fase 3 — Dados GTFS e grafo
- [ ] Fase 4 — Procura determinística
- [ ] Fase 5 — Modelo de Markov
- [ ] Fase 6 — Procura + Markov
- [ ] Fase 7 — Relatório e apresentação