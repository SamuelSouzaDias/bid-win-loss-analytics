# Bid Win/Loss Analytics

*[Versão em português](README.pt-BR.md)*

**A B2B facilities-services company wins 31% of the bids it closes — but only 26% of the revenue it bids for. This project explains the gap, and finds that the most obvious answer in the data is an artefact.**

---

## The business question

Sales leadership wanted a single number: our win rate, broken down by segment, region and account executive, so they could see where to intervene.

That number turned out to be the least useful thing in the dataset. Two findings mattered more:

**1. A migration artefact was disguised as sales performance.**

The first cut of the data showed Executive 4 closing 25.4% of bids against a 31.3% company average — a clear underperformer, across a large enough sample to look conclusive. Publishing that would have been wrong.

58% of all bids share an identical creation timestamp with dozens or hundreds of other rows: they were bulk-loaded, not entered as they happened. The largest single batch contains 355 bids registered in the same second. Those batches are concentrated in one executive's portfolio and behave nothing like organically entered bids:

| Channel | Closed bids | Win rate |
|---|---|---|
| Bulk-loaded | 649 | 18.3% |
| Organically entered | 470 | 48.4% |

Isolating the effect moves Executive 4 from 25.4% to **42.2%** — from worst performer to slightly above the organic average. Every segment and regional ranking shifts the same way.

**2. Win rate by count hides a pricing problem.**

The company wins small contracts and loses large ones:

| Contract value quartile | Win rate |
|---|---|
| Q1 (smallest) | 41.0% |
| Q2 | 37.3% |
| Q3 | 24.4% |
| Q4 (largest) | 22.6% |

Counting bids gives a 31.3% win rate. Weighting by contract value gives **26.4%**. The five-point gap is entirely large deals being lost, and the recorded loss reasons point the same way: **87% of them are price or cost-structure related.**

---

## The data quality problem underneath both

The field that would settle the question is almost empty. Only **8.5% of losses have a recorded reason** (67 of 789).

The other 92% are attributed to a competitor named `Competitor 1` — 721 losses, **zero** of which carry a loss reason. Every other competitor in the dataset has a reason recorded 100% of the time. `Competitor 1` is not a competitor; it is the system's default value, written whenever nobody completed the post-mortem.

This is the project's primary recommendation: a loss reason should be mandatory at bid closure. The company is currently losing roughly 790 bids per cycle without knowing why.

---

## Architecture

Medallion architecture on Databricks, PySpark, Delta tables registered in Unity Catalog.

```
raw/ (Volume)          bronze.bid          silver.bid           gold.bid
  bids.xlsx      ->     bids         ->     bids_clean     ->    bid_performance
  clients.xlsx   ->     clients      ->     clients_clean        loss_reasons
```

| Layer | Responsibility |
|---|---|
| **Bronze** | Ingest as-is. No casting, no cleaning. Schema drift accepted and logged. |
| **Silver** | Type casting, `'null'` string to true NULL, sentinel dates resolved, duplicate client rows collapsed, `is_bulk_load` flag derived. |
| **Gold** | Business aggregates: win rate by count and by value, segmentation, loss reason distribution, open pipeline. |

### Design decisions worth naming

**Schema drift is accepted at Bronze, not rejected.** The source is a manual Excel export whose columns change without notice. Failing the load would stop the pipeline for a cosmetic change; accepting drift and validating at Silver keeps ingestion resilient and puts the contract where it belongs.

**`is_bulk_load` is derived, not given.** Any row whose `created_at` is shared by ten or more other rows is flagged. Every downstream metric is reported both with and without it. This is the single transformation that changes the conclusions.

**Redundant columns are preserved in Bronze.** `created_at` and `created_at_str` carry the same information; the string version is dropped at Silver, not at ingestion, so the raw layer stays a faithful copy of the source.

---

## Data

**The data in this repository is synthetic.** It is produced by [`generate_bid_data.py`](src/generate_bid_data.py), seeded at 42, so every figure above is reproducible by anyone who clones the repo.

The generator does not produce clean data. It deliberately reproduces the pathologies observed in a production bidding system:

- Bulk-loaded records sharing an identical creation timestamp
- A placeholder competitor value that masks missing post-mortem data
- A loss reason field populated for a small minority of losses
- Closure timestamps written seconds apart, from records closed in a single sitting
- Redundant raw and string-formatted date columns
- Sentinel dates (`2999-12-31`) and literal `'null'` strings
- Duplicate client rows from contract renewals

Modelling those pathologies deliberately is the point. Clean synthetic data would make the analysis trivial and the pipeline pointless.

### Schema

`bids` — 1,600 rows

| Column | Description |
|---|---|
| `bid_id` | Bid identifier |
| `created_at`, `created_at_str` | Registration timestamp; string form is redundant |
| `is_confirmed_date` | 1 = `bid_date` is confirmed, 0 = forecast (averages 19 days out) |
| `bid_date` | Bid date |
| `closed_at`, `closed_at_str` | Closure timestamp; `-` when still open |
| `outcome` | 1 won, 0 lost, null still open |
| `loss_reason` | Post-mortem reason; populated for 8.5% of losses |
| `competitor_name` | Winning competitor; `Competitor 1` is the system default |
| `client_id` | Foreign key to `clients` |
| `contract_value_brl` | Monthly contract value |

`clients` — 1,537 rows, 1,450 unique

| Column | Description |
|---|---|
| `client_id` | Client identifier |
| `contract_name`, `status` | Contract label and lifecycle state |
| `start_date`, `end_date` | Contract dates; `2999-12-31` marks open-ended |
| `state`, `city`, `segment` | Location and industry |
| `account_executive`, `director`, `manager`, `coordinator` | Commercial hierarchy |

---

## What this analysis cannot tell you

Stating these plainly matters more than the charts.

**Sales cycle length is not measurable.** More than half of all closure timestamps were written in sequence, seconds apart, in bulk-closing sessions months after the fact. Any metric derived from `closed_at - bid_date` would be fiction. It is deliberately absent from the Gold layer.

**The loss reason sample is not random.** The 67 bids with a recorded reason are those someone chose to investigate. Larger or more contested deals are plausibly over-represented, so the 87% price finding is a strong signal, not a population estimate.

**Contract value is monthly, not total.** Without contract duration, a twelve-month deal and a five-year deal of the same monthly value are indistinguishable. The value-weighted win rate is therefore directional.

**No bid cost is recorded.** Win rate cannot be turned into return on bidding effort, which is what a commercial director actually needs to prioritise.

---

## Recommendations

1. **Make loss reason mandatory at closure.** Nothing else in this list is worth doing until the 92% blind spot closes.
2. **Separate migration data from operational data.** Bulk-loaded records should carry a source flag at ingestion rather than be inferred later from timestamp collisions.
3. **Review pricing on large contracts.** Q4-value bids convert at roughly half the rate of Q1, and recorded losses are overwhelmingly price-driven.
4. **Capture contract duration and bid cost.** Both are prerequisites for measuring return on bidding effort.
5. **Report win rate weighted by value alongside the count-based figure.** Reporting only the count overstates commercial performance by five points.

---

## Reproducing this

```bash
git clone <repository-url>
cd bid-win-loss-analytics
pip install -r requirements.txt

python src/generate_bid_data.py --seed 42 --outdir data/raw
```

Then run the notebooks in order:

```
notebooks/
  00_bronze_bids.ipynb
  01_bronze_clients.ipynb
  02_silver_bids.ipynb
  03_gold_bid_performance.ipynb
  04_analysis.ipynb
```

The notebooks target Databricks with Unity Catalog. To run them elsewhere, change the volume path at the top of `00_bronze_bids.ipynb`.

---

## Stack

Databricks · PySpark · Delta Lake · Unity Catalog · Python (pandas, numpy) · Power BI
