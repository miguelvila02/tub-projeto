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

## Registo de atrasos

Preencher `dados/atrasos/registo_atrasos.csv`, uma linha por paragem observada.
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
