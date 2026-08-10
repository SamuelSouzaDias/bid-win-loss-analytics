"""
Synthetic data generator for the Bid Performance Insights project.

Produces two source files that mimic a real B2B facilities-services bidding
system, including the data-quality pathologies commonly found in production
CRM exports:

  1. Bulk-loaded records sharing an identical creation timestamp
  2. A placeholder competitor value that masks missing post-mortem data
  3. A loss-reason field populated for only a small fraction of losses
  4. Redundant raw/string date columns
  5. Sentinel dates and literal 'null' strings

No real company data is used. Every value is generated.

Usage:  python generate_bid_data.py [--seed 42] [--outdir ./data/raw]
"""

import argparse
import random
from datetime import datetime, timedelta, date

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

N_CLIENTS = 1_450
N_BIDS = 1_600

# Share of bids that arrive as bulk imports rather than organic entry.
BULK_SHARE = 0.58

# Probability a closed bid is won, by acquisition channel.
WIN_RATE_ORGANIC = 0.55
WIN_RATE_BULK = 0.255

# Share of all bids still awaiting an outcome.
OPEN_SHARE = 0.30

# Share of losses that received an actual post-mortem.
POST_MORTEM_SHARE = 0.085

PLACEHOLDER_COMPETITOR = "Competitor 1"

START = date(2024, 11, 1)
END = date(2026, 3, 31)

SEGMENTS = {
    # segment: (relative weight, baseline win-rate multiplier, value tier)
    "MANUFACTURING":        (0.13, 1.45, "high"),
    "HOSPITAL-CLINIC-LAB":  (0.10, 1.30, "high"),
    "SHOPPING CENTRE":      (0.08, 1.03, "mid"),
    "RETAIL":               (0.09, 1.03, "mid"),
    "CORPORATE PROPERTY":   (0.08, 1.03, "mid"),
    "ENERGY":               (0.04, 1.06, "high"),
    "TRANSPORT-LOGISTICS":  (0.05, 1.13, "mid"),
    "INSURANCE":            (0.04, 1.00, "mid"),
    "AUTOMOTIVE":           (0.04, 0.83, "high"),
    "PUBLIC SECTOR":        (0.13, 0.60, "low"),
    "FINANCIAL SERVICES":   (0.17, 0.27, "low"),
    "RESIDENTIAL PROPERTY": (0.05, 0.47, "low"),
}

STATES = ["SP", "PR", "RJ", "MG", "RS", "SC", "PA", "BA", "GO", "PE"]
STATE_WEIGHTS = [0.34, 0.28, 0.09, 0.07, 0.06, 0.04, 0.04, 0.03, 0.03, 0.02]

CITIES = {
    "SP": ["SAO PAULO", "CAMPINAS", "GUARULHOS", "SANTO ANDRE", "SOROCABA"],
    "PR": ["CURITIBA", "LONDRINA", "MARINGA", "CASCAVEL"],
    "RJ": ["RIO DE JANEIRO", "NITEROI", "DUQUE DE CAXIAS"],
    "MG": ["BELO HORIZONTE", "UBERLANDIA", "CONTAGEM"],
    "RS": ["PORTO ALEGRE", "CAXIAS DO SUL"],
    "SC": ["FLORIANOPOLIS", "JOINVILLE"],
    "PA": ["BELEM", "ANANINDEUA"],
    "BA": ["SALVADOR", "FEIRA DE SANTANA"],
    "GO": ["GOIANIA", "ANAPOLIS"],
    "PE": ["RECIFE", "JABOATAO"],
}

# Loss reasons, weighted so that price-related causes dominate.
LOSS_REASONS = [
    ("Client prioritised cost reduction", 0.44),
    ("Cost structure incompatible with client budget", 0.11),
    ("Bid cancelled by client", 0.10),
    ("Competitor offered lower price", 0.08),
    ("Financial proposal not competitive", 0.08),
    ("Cost structure incompatible", 0.06),
    ("Unfavourable commercial terms", 0.05),
    ("Scope did not match expectations", 0.03),
    ("Incumbent held established relationship", 0.02),
    ("Bid suspended / postponed", 0.01),
    ("Insufficient information from client", 0.01),
    ("Reason not recorded", 0.01),
]

VALUE_TIERS = {
    # tier: (lognormal mean, sigma) for monthly contract value in BRL
    "low":  (10.95, 0.80),
    "mid":  (11.20, 0.82),
    "high": (11.45, 0.85),
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def iso_utc(dt: datetime) -> str:
    """Match the raw export format: 2025-05-27T16:06:34.000+00:00"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000+00:00")


def random_datetime(rng, start: date, end: date) -> datetime:
    span = (end - start).days
    d = start + timedelta(days=int(rng.integers(0, span)))
    return datetime(d.year, d.month, d.day,
                    int(rng.integers(7, 20)),
                    int(rng.integers(0, 60)),
                    int(rng.integers(0, 60)))


def business_shift(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

def build_clients(rng) -> pd.DataFrame:
    seg_names = list(SEGMENTS)
    seg_weights = np.array([SEGMENTS[s][0] for s in seg_names], dtype=float)
    seg_weights = seg_weights / seg_weights.sum()

    # Commercial hierarchy: directors -> managers -> coordinators, and a
    # separate account-executive population.
    directors = [f"Director {i}" for i in range(1, 11)]
    managers = [f"Manager {i}" for i in range(1, 37)]
    coordinators = [f"Coordinator {i}" for i in range(1, 41)]
    executives = [f"Executive {i}" for i in range(1, 10)]

    # Executive 4 owns the portfolio that will later be bulk-imported.
    exec_weights = np.array([0.09, 0.05, 0.04, 0.30, 0.07, 0.13, 0.06, 0.09, 0.17])
    exec_weights = exec_weights / exec_weights.sum()

    ids = rng.choice(np.arange(100, 9_999), size=N_CLIENTS, replace=False)
    rows = []
    for cid in ids:
        segment = rng.choice(seg_names, p=seg_weights)
        state = rng.choice(STATES, p=STATE_WEIGHTS)

        # Financial-services and public-sector clients skew to Executive 4's
        # region, which is what makes the bulk-import confound believable.
        if segment in ("FINANCIAL SERVICES", "PUBLIC SECTOR") and rng.random() < 0.62:
            state = "PR"
            executive = "Executive 4"
        else:
            executive = rng.choice(executives, p=exec_weights)

        city = rng.choice(CITIES[state])
        status = "Active" if rng.random() < 0.72 else "Inactive"

        start_dt = random_datetime(rng, date(2019, 1, 1), date(2026, 1, 1)).date()
        if status == "Active" and rng.random() < 0.28:
            end_dt = date(2999, 12, 31)          # open-ended sentinel
        else:
            end_dt = start_dt + timedelta(days=int(rng.integers(180, 2200)))

        rows.append({
            "client_id": int(cid),
            "contract_name": f"{segment.split('-')[0].strip().lower()} {rng.integers(1, 400)}",
            "status": status,
            "start_date": "-" if rng.random() < 0.04 else start_dt,
            "end_date": end_dt,
            "state": "null" if rng.random() < 0.03 else state,
            "city": "null" if rng.random() < 0.03 else city,
            "segment": segment,
            "account_executive": executive,
            "director": rng.choice(directors),
            "manager": rng.choice(managers),
            "coordinator": rng.choice(coordinators),
        })

    df = pd.DataFrame(rows)

    # A handful of clients appear twice (contract renewals recorded as new rows)
    dupes = df.sample(frac=0.06, random_state=int(rng.integers(0, 10_000))).copy()
    dupes["contract_name"] = dupes["contract_name"] + " (renewal)"
    return pd.concat([df, dupes], ignore_index=True)


# --------------------------------------------------------------------------
# Bids
# --------------------------------------------------------------------------

def build_bids(rng, clients: pd.DataFrame) -> pd.DataFrame:
    unique_clients = clients.drop_duplicates("client_id").set_index("client_id")

    n_bulk = int(N_BIDS * BULK_SHARE)
    n_organic = N_BIDS - n_bulk

    # ---- Bulk batches -----------------------------------------------------
    # Large portfolios ingested in one transaction. Sizes chosen so a few
    # dominate, mirroring what a migration actually looks like.
    batch_sizes, remaining = [], n_bulk
    for size in (355, 220, 95, 50, 48, 44):
        if remaining <= 0:
            break
        take = min(size, remaining)
        batch_sizes.append(take)
        remaining -= take
    while remaining > 0:
        take = min(int(rng.integers(10, 30)), remaining)
        batch_sizes.append(take)
        remaining -= take

    # Bulk batches draw from concentrated portfolios (Executive 4 / PR /
    # financial services), which is precisely the confound to be discovered.
    bulk_pool = unique_clients[
        (unique_clients["account_executive"] == "Executive 4")
        | (unique_clients["segment"].isin(["FINANCIAL SERVICES", "PUBLIC SECTOR"]))
    ].index.to_numpy()
    if len(bulk_pool) < n_bulk:
        bulk_pool = np.concatenate([bulk_pool, unique_clients.index.to_numpy()])

    organic_pool = unique_clients.index.to_numpy()

    records, bid_id = [], 100
    for size in batch_sizes:
        stamp = random_datetime(rng, START, END)
        chosen = rng.choice(bulk_pool, size=size, replace=True)
        for cid in chosen:
            bid_id += 1
            records.append((bid_id, stamp, int(cid), "bulk"))

    for _ in range(n_organic):
        bid_id += 1
        stamp = random_datetime(rng, START, END)
        cid = int(rng.choice(organic_pool))
        records.append((bid_id, stamp, cid, "organic"))

    rng.shuffle(records)

    # ---- Contract values --------------------------------------------------
    # Generated up front so the size effect can be expressed as a percentile.
    # Without this the segment effect swamps it, because the high-value
    # segments happen to be the easiest to win.
    values = []
    for _, _, client_id, _ in records:
        tier = SEGMENTS[unique_clients.loc[client_id, "segment"]][2]
        mu, sigma = VALUE_TIERS[tier]
        values.append(round(float(min(np.exp(rng.normal(mu, sigma)), 4_000_000)), 2))
    value_pct = pd.Series(values).rank(pct=True).to_numpy()

    # ---- Outcomes ---------------------------------------------------------
    rows = []
    for i, (bid_id, created_at, client_id, channel) in enumerate(records):
        client = unique_clients.loc[client_id]
        segment = client["segment"]
        seg_mult = SEGMENTS[segment][1]
        tier = SEGMENTS[segment][2]

        # is_confirmed_date: 0 means bid_date is a forecast, not a fact.
        confirmed = 1 if rng.random() > 0.057 else 0
        if confirmed:
            bid_date = datetime(created_at.year, created_at.month, created_at.day)
        else:
            bid_date = datetime(created_at.year, created_at.month, created_at.day) \
                       + timedelta(days=int(rng.integers(5, 45)))

        still_open = rng.random() < OPEN_SHARE
        base_rate = WIN_RATE_BULK if channel == "bulk" else WIN_RATE_ORGANIC
        win_prob = float(np.clip(base_rate * seg_mult, 0.01, 0.95))

        # Contract value. Larger contracts are materially harder to win, so a
        # value-weighted win rate lands below the count-based one. That gap is
        # invisible unless the analyst thinks to weight by revenue.
        value = values[i]
        size_factor = 1.55 - 1.10 * float(value_pct[i])
        win_prob = float(np.clip(win_prob * size_factor, 0.01, 0.95))

        if still_open:
            outcome, closed_at = None, None
        else:
            outcome = 1 if rng.random() < win_prob else 0
            closed_at = business_shift(created_at, int(rng.integers(20, 300)))

        rows.append({
            "bid_id": bid_id,
            "_created_at": created_at,
            "_closed_at": closed_at,
            "is_confirmed_date": confirmed,
            "_bid_date": bid_date,
            "outcome": outcome,
            "client_id": client_id,
            "contract_value_brl": value,
            "_channel": channel,
        })

    df = pd.DataFrame(rows)

    # ---- Bulk closure artefact -------------------------------------------
    # Closures performed in a single sitting produce timestamps seconds apart.
    # Any cycle-time metric derived from these is meaningless.
    closed = np.array(df[df["_closed_at"].notna()].index)
    rng.shuffle(closed)
    n_seq = int(len(closed) * 0.55)
    cursor = 0
    while cursor < n_seq:
        run = min(int(rng.integers(8, 60)), n_seq - cursor)
        batch_idx = closed[cursor:cursor + run]
        # The sitting has to postdate every bid it closes, otherwise the file
        # carries impossible records — a defect, not a realistic pathology.
        latest = max(df.at[j, "_created_at"] for j in batch_idx)
        anchor = latest + timedelta(days=int(rng.integers(15, 240)),
                                    hours=int(rng.integers(0, 10)))
        for offset in range(run):
            idx = closed[cursor + offset]
            df.at[idx, "_closed_at"] = anchor + timedelta(seconds=offset * int(rng.integers(9, 22)))
        cursor += run

    # ---- Loss reasons and competitors ------------------------------------
    reasons = [r for r, _ in LOSS_REASONS]
    reason_p = np.array([p for _, p in LOSS_REASONS])
    reason_p = reason_p / reason_p.sum()

    competitors = [f"Competitor {i}" for i in range(2, 16)]
    comp_p = np.array([0.05, 0.03, 0.03, 0.10, 0.09, 0.06, 0.04,
                       0.03, 0.04, 0.05, 0.14, 0.05, 0.24, 0.05])
    comp_p = comp_p / comp_p.sum()

    loss_reason, competitor = [], []
    for _, r in df.iterrows():
        if r["outcome"] == 0:
            if rng.random() < POST_MORTEM_SHARE:
                loss_reason.append(rng.choice(reasons, p=reason_p))
                competitor.append(rng.choice(competitors, p=comp_p))
            else:
                # No post-mortem: the system writes its default value.
                loss_reason.append(None)
                competitor.append(PLACEHOLDER_COMPETITOR)
        else:
            loss_reason.append(None)
            competitor.append(None)

    df["loss_reason"] = loss_reason
    df["competitor_name"] = competitor

    # ---- Raw-export shaping ----------------------------------------------
    out = pd.DataFrame({
        "bid_id": df["bid_id"],
        "created_at": df["_created_at"].map(iso_utc),
        "created_at_str": df["_created_at"].dt.strftime("%-m/%-d/%y %-H:%M"),
        "is_confirmed_date": df["is_confirmed_date"],
        "bid_date": df["_bid_date"].map(iso_utc),
        "closed_at": df["_closed_at"].map(lambda x: iso_utc(x) if pd.notna(x) else "-"),
        "closed_at_str": df["_closed_at"].map(
            lambda x: x.strftime("%-m/%-d/%y %-H:%M") if pd.notna(x) else "null"),
        "outcome": df["outcome"].map(lambda x: "null" if pd.isna(x) else int(x)),
        "loss_reason": df["loss_reason"].fillna("null"),
        "competitor_name": df["competitor_name"].fillna("null"),
        "client_id": df["client_id"],
        "contract_value_brl": df["contract_value_brl"],
    })
    return out.sort_values("bid_id").reset_index(drop=True)


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    random.seed(args.seed)

    clients = build_clients(rng)
    bids = build_bids(rng, clients)

    clients.to_excel(f"{args.outdir}/clients.xlsx", index=False, sheet_name="Clients")
    bids.to_excel(f"{args.outdir}/bids.xlsx", index=False, sheet_name="Bronze")
    clients.to_csv(f"{args.outdir}/clients.csv", index=False)
    bids.to_csv(f"{args.outdir}/bids.csv", index=False)

    print(f"clients: {clients.shape}   bids: {bids.shape}")


if __name__ == "__main__":
    main()
