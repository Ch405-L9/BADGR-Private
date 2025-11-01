
#!/usr/bin/env python3
"""
BADGRTech Keyword Intelligence Manager
Phase: R8+ Lead Discovery Expansion
Functions:
- Merge new keyword queues into master
- Dedupe and validate schema
- Update priorities based on yield performance
- Generate next-run ranked list
"""

import csv, os, datetime
from pathlib import Path
import pandas as pd

SEED = "data/keywords_seed.csv"
QUEUE = "data/keywords_queue.csv"
YIELD = "data/keywords_yield.log"
OUT = "data/keywords_master_next.csv"
SCHEMA = ["region","subregion","bucket","stage","priority","has_operator","recommended_filters","keyword"]

def read_csv_safe(path):
    if not os.path.exists(path):
        return pd.DataFrame(columns=SCHEMA)
    return pd.read_csv(path, dtype=str).fillna("")

def normalize(df):
    if df.empty:
        for c in SCHEMA:
            if c not in df.columns: df[c] = ""
        return df
    df = df[[c for c in SCHEMA if c in df.columns]].copy()
    df["priority"] = df["priority"].astype(str).str.extract(r"(\d+)").fillna("70").astype(int)
    df["keyword"] = df["keyword"].astype(str).str.strip().str.lower()
    df["region"] = df["region"].astype(str).str.strip().str.lower()
    df["bucket"] = df["bucket"].astype(str).str.strip().str.lower()
    df.drop_duplicates(subset=["keyword","region","bucket"], inplace=True)
    return df

def adjust_priorities(df, yield_df):
    if yield_df.empty or df.empty:
        return df
    # Normalize yield types
    for col in ["verified_hits","linkedin_hits","contactpage_hits","total_searches"]:
        if col in yield_df.columns:
            yield_df[col] = yield_df[col].fillna("0").astype(str).str.extract(r"(\d+)").fillna("0").astype(int)
    if "average_cwv_score" in yield_df.columns:
        yield_df["average_cwv_score"] = yield_df["average_cwv_score"].fillna("0").astype(str).str.extract(r"(\d+(?:\.\d+)?)").fillna("0").astype(float)

    # Apply boosts
    for _, row in yield_df.iterrows():
        kw = str(row.get("keyword","")).lower().strip()
        if not kw: continue
        matches = df["keyword"] == kw
        if not matches.any(): continue
        base = df.loc[matches, "priority"].astype(int)
        delta = (int(row.get("verified_hits",0)) * 2 +
                 int(row.get("linkedin_hits",0)) +
                 int(row.get("contactpage_hits",0))) - float(row.get("average_cwv_score",0.0)) * 0.5
        df.loc[matches, "priority"] = (base + delta).clip(upper=100)
    return df

def main():
    seed_df = normalize(read_csv_safe(SEED))
    queue_df = normalize(read_csv_safe(QUEUE))

    # Load yield log as CSV; skip header line safely
    if os.path.exists(YIELD):
        try:
            yield_df = pd.read_csv(YIELD, dtype=str)
        except Exception:
            yield_df = pd.DataFrame()
    else:
        yield_df = pd.DataFrame()

    merged = pd.concat([seed_df, queue_df], ignore_index=True)
    merged = normalize(merged)

    if not yield_df.empty:
        merged = adjust_priorities(merged, yield_df)

    merged.sort_values(by=["priority","region","bucket","keyword"],
                       ascending=[False,True,True,True], inplace=True)
    Path(os.path.dirname(OUT)).mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT, index=False)
    print(f"✅ Next-run keyword list written → {OUT} (rows={len(merged)})")

    Path("logs").mkdir(exist_ok=True)
    with open("logs/keywords_manage.log","a") as log:
        log.write(f"{datetime.datetime.now(datetime.timezone.utc).isoformat()} merged={len(seed_df)} new={len(queue_df)} yield_used={not yield_df.empty}\n")

if __name__ == "__main__":
    main()
