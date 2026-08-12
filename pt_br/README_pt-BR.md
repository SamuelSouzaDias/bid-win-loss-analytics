# Bid Win/Loss Analytics

*[English version](README.md)*

> Esta é a versão em português do README. O projeto — código, notebooks, nomes de tabelas e colunas — está inteiramente em inglês.

**Uma empresa de facilities B2B ganha 32% das propostas que fecha — mas apenas 25% da receita pela qual concorre. Este projeto explica a diferença, e mostra que a resposta mais óbvia nos dados é um artefato.**

---

## A pergunta de negócio

A liderança comercial queria um número: a taxa de vitória, aberta por segmento, região e executivo de contas, para saber onde intervir.

Esse número acabou sendo a coisa menos útil da base. Dois achados importaram mais:

**1. Um artefato de migração estava se passando por desempenho comercial.**

O primeiro corte mostrava o Executivo 4 fechando 26,0% das propostas contra uma média de 31,8% da empresa — um caso claro de baixo desempenho, numa amostra grande o bastante para parecer conclusiva. Publicar isso teria sido um erro.

58% de todas as propostas compartilham o mesmo timestamp de criação com dezenas ou centenas de outras linhas: foram carregadas em lote, não registradas conforme aconteciam. O maior lote isolado tem 355 propostas criadas no mesmo segundo. Esses lotes estão concentrados na carteira de um executivo e se comportam de forma completamente diferente das propostas orgânicas:

| Origem | Propostas fechadas | Taxa de vitória |
|---|---|---|
| Carga em lote | 660 | 20,0% |
| Registro orgânico | 481 | 48,0% |

Isolando o efeito, o Executivo 4 passa de 26,0% para **45,5%** — de pior desempenho para bem acima da média orgânica. Todos os rankings por segmento e região se deslocam da mesma forma.

![Taxa de vitória: propostas em lote vs orgânicas, e a taxa do Executivo 4 com e sem carga em lote](assets/migration_artefact.png)

Isso não é só uma comparação bruta — o lote de carga em massa está concentrado nos dois segmentos que menos convertem (Financial Services, Public Sector), então a diferença poderia, em princípio, ser mix de segmento disfarçado de artefato de migração. Uma regressão logística controlando por segmento, estado e valor do contrato mostra que não é: o odds ratio ajustado para `is_bulk_load` é **0,20** (IC 95% 0,15–0,28, p = 3,6×10⁻²³), próximo do 0,27 sem ajuste nenhum. O efeito é real, não um proxy de quem calhou de ser carregado em lote. Modelo completo em [`04_analysis.ipynb`](04_analysis.ipynb).

**2. A taxa de vitória por contagem esconde um problema de precificação.**

A empresa ganha os contratos pequenos e perde os grandes:

| Quartil de valor do contrato | Taxa de vitória |
|---|---|
| Q1 (menores) | 39,0% |
| Q2 | 34,0% |
| Q3 | 30,2% |
| Q4 (maiores) | 24,4% |

![Taxa de vitória por quartil de valor de contrato, caindo de ~39% para ~24% conforme o tamanho do negócio aumenta](assets/win_rate_by_value.png)

Contando propostas, a taxa de vitória é 31,8%. Ponderando por valor de contrato, é **24,9%**. Os sete pontos de diferença são inteiramente contratos grandes sendo perdidos — e os motivos de perda registrados apontam na mesma direção: **85% são relacionados a preço ou estrutura de custos.**

---

## O problema de qualidade de dados por trás dos dois

O campo que resolveria a questão está quase vazio. Apenas **7,6% das perdas têm motivo registrado** (59 de 778).

Os outros 92% estão atribuídos a um concorrente chamado `Competitor 1` — 719 perdas, **nenhuma** delas com motivo. Todos os demais concorrentes da base têm motivo preenchido em 100% dos casos. `Competitor 1` não é um concorrente: é o valor padrão do sistema, gravado sempre que ninguém fez a apuração pós-proposta.

Essa é a principal recomendação do projeto: o motivo de perda precisa ser obrigatório no fechamento. Hoje a empresa perde cerca de 780 propostas por ciclo sem saber por quê.

---

## Arquitetura

Arquitetura medallion no Databricks, com PySpark e tabelas Delta registradas no Unity Catalog.

```
raw/ (Volume)          bronze.bid          silver.bid           gold.bid
  bids.xlsx      ->     bids         ->     bids_clean     ->    bid_performance
  clients.xlsx   ->     clients      ->     clients_clean        loss_reasons
```

| Camada | Responsabilidade |
|---|---|
| **Bronze** | Ingestão fiel à origem. Sem cast, sem limpeza. Mudança de schema é aceita e registrada. |
| **Silver** | Tipagem, conversão de `'null'` textual em NULL real, tratamento de datas sentinela, clientes modelados como dimensão SCD Type 2, criação do flag `is_bulk_load`. |
| **Gold** | Agregados de negócio: taxa de vitória por contagem e por valor, segmentações, distribuição de motivos, pipeline em aberto. |

### Decisões de projeto que valem ser explicitadas

**A mudança de schema é aceita no Bronze, não rejeitada.** A origem é uma exportação manual de Excel cujas colunas mudam sem aviso. Falhar a carga interromperia o pipeline por uma alteração cosmética; aceitar a variação e validar no Silver mantém a ingestão resiliente e coloca o contrato de dados onde ele deve estar.

**O `is_bulk_load` é derivado, não fornecido.** Toda linha cujo `created_at` é compartilhado por dez ou mais outras recebe o flag. Todas as métricas seguintes são reportadas com e sem esses registros. É a única transformação que muda as conclusões.

**`clients` é uma dimensão SCD Type 2, associada por ponto no tempo.** Uma renovação é um segundo período de contrato para o mesmo `client_id`, não uma linha duplicada pra descartar. Toda versão é mantida com `valid_from`/`valid_to` explícitos, e o Gold associa cada proposta à versão que estava vigente *no momento em que a proposta foi criada* — não à versão mais recente hoje. Colapsar para "a linha mais recente", a abordagem anterior, teria descartado histórico de contrato real e (pior) atribuído os dados atuais do cliente a uma proposta de anos atrás, quando eles ainda não valiam.

**Colunas redundantes são preservadas no Bronze.** `created_at` e `created_at_str` carregam a mesma informação; a versão texto é descartada no Silver, não na ingestão, para que a camada bruta continue sendo uma cópia fiel da origem.

---

## Dados

**Os dados deste repositório são sintéticos.** São produzidos por [`generate_bid_data.py`](src/generate_bid_data.py), com semente fixa em 42, de modo que todos os números acima são reprodutíveis por qualquer pessoa que clonar o repositório.

O gerador não produz dados limpos. Ele reproduz deliberadamente as patologias observadas em um sistema de propostas em produção:

- Registros carregados em lote, compartilhando o mesmo timestamp de criação
- Um valor padrão de concorrente que mascara a ausência de apuração
- Campo de motivo de perda preenchido em uma minoria dos casos
- Timestamps de fechamento separados por segundos, de registros encerrados numa única sessão
- Colunas de data duplicadas, em formato bruto e texto
- Datas sentinela (`2999-12-31`) e strings literais `'null'`
- Um segundo período de contrato para clientes que renovam, sem sobreposição com o primeiro

Modelar essas patologias de propósito é justamente o ponto. Dados sintéticos limpos tornariam a análise trivial e o pipeline desnecessário.

### Schema

`bids` — 1.600 linhas

| Coluna | Descrição |
|---|---|
| `bid_id` | Identificador da proposta |
| `created_at`, `created_at_str` | Timestamp de cadastro; a versão texto é redundante |
| `is_confirmed_date` | 1 = `bid_date` confirmada, 0 = previsão (em média 19 dias à frente) |
| `bid_date` | Data da proposta |
| `closed_at`, `closed_at_str` | Timestamp de fechamento; `-` quando em aberto |
| `outcome` | 1 ganhou, 0 perdeu, null em aberto |
| `loss_reason` | Motivo apurado; preenchido em 7,6% das perdas |
| `competitor_name` | Concorrente vencedor; `Competitor 1` é o padrão do sistema |
| `client_id` | Chave estrangeira para `clients` |
| `contract_value_brl` | Valor mensal do contrato |

`clients` — 1.519 linhas (bruto), 1.450 clientes únicos. O Silver adiciona `valid_from`, `valid_to`, `is_current` e uma chave substituta `client_sk` em cima das colunas abaixo — veja [Decisões de projeto](#decisões-de-projeto-que-valem-ser-explicitadas).

| Coluna | Descrição |
|---|---|
| `client_id` | Identificador do cliente |
| `contract_name`, `status` | Rótulo do contrato e situação |
| `start_date`, `end_date` | Datas do contrato; `2999-12-31` indica prazo indeterminado |
| `state`, `city`, `segment` | Localização e segmento |
| `account_executive`, `director`, `manager`, `coordinator` | Hierarquia comercial |

---

## O que esta análise não permite afirmar

Declarar isso explicitamente importa mais que os gráficos.

**O ciclo de venda não é mensurável.** Mais da metade dos timestamps de fechamento foi gravada em sequência, com segundos de intervalo, em sessões de encerramento em massa meses após o fato. Qualquer métrica derivada de `closed_at - bid_date` seria ficção. Ela está deliberadamente ausente da camada Gold.

**A amostra de motivos não é aleatória.** As 59 propostas com motivo registrado são aquelas que alguém decidiu investigar. É plausível que negócios maiores ou mais disputados estejam super-representados, então os 85% relacionados a preço são um sinal forte, não uma estimativa populacional.

**O valor do contrato é mensal, não total.** Sem a duração, um contrato de doze meses e outro de cinco anos com o mesmo valor mensal são indistinguíveis. A taxa ponderada por valor é, portanto, direcional.

**Não há custo de proposta registrado.** Sem ele, a taxa de vitória não se converte em retorno sobre esforço comercial — que é o que um diretor comercial precisa para priorizar.

**Cerca de 6% das propostas não conseguem ser associadas a um período de contrato do cliente.** `clients` é modelado como uma dimensão SCD Type 2 (um cliente pode ter mais de uma versão de contrato ao longo do tempo), e cada proposta é associada à versão que estava vigente *no momento em que foi criada* — não apenas à versão mais recente hoje. Cerca de 6% das propostas não caem em nenhuma janela de versão conhecida, seja porque a data de início do contrato do cliente é desconhecida, seja porque a proposta é anterior ao início de contrato mais antigo registrado. Essas propostas mantêm seu resultado e valor, mas aparecem sem segmento/estado/executivo associado, em vez de serem forçadas a um período errado silenciosamente.

---

## Recomendações

1. **Tornar o motivo de perda obrigatório no fechamento.** Nada mais nesta lista vale a pena enquanto o ponto cego de 92% existir.
2. **Separar dados de migração de dados operacionais.** Registros carregados em lote deveriam trazer um indicador de origem na ingestão, em vez de serem inferidos depois por colisão de timestamp.
3. **Revisar a precificação de contratos grandes.** Propostas do quartil superior de valor convertem a aproximadamente metade da taxa do quartil inferior, e as perdas registradas são majoritariamente de preço.
4. **Capturar duração do contrato e custo da proposta.** Ambos são pré-requisitos para medir retorno sobre esforço comercial.
5. **Reportar a taxa de vitória ponderada por valor ao lado da contagem.** Reportar apenas a contagem superestima o desempenho comercial em sete pontos.

---

## Como reproduzir

```bash
git clone <url-do-repositorio>
cd bid-win-loss-analytics
pip install -r requirements.txt

python src/generate_bid_data.py --seed 42 --outdir data/raw
```

Depois execute os notebooks nesta ordem:

```
notebooks/
  00_bronze_bids.ipynb
  01_bronze_clients.ipynb
  02_silver_bids.ipynb
  03_gold_bid_performance.ipynb
  04_analysis.ipynb
```

Os notebooks são escritos para Databricks com Unity Catalog. Para rodar em outro ambiente, altere o caminho do volume no topo de `00_bronze_bids.ipynb`.

**Cada notebook também existe em português**, com sufixo `_pt-BR` (`00_bronze_bids_pt-BR.ipynb`, e assim por diante). É o mesmo código, mesmas tabelas, mesmos resultados — só o markdown explicativo e os comentários foram traduzidos. Os nomes de tabela, coluna e variável ficam em inglês de propósito, então as duas versões leem e gravam exatamente nas mesmas tabelas do Unity Catalog; não é um pipeline paralelo, é o mesmo pipeline documentado nos dois idiomas.

---

## Stack

Databricks · PySpark · Delta Lake · Unity Catalog · Python (pandas, numpy) · Power BI
