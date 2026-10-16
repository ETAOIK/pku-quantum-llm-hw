"""Read-only L2 audit and causal five-second feature panel."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT.parents[1] / "第三周实践课" / "sse50_20260923"
HORIZONS = (15, 30, 60, 180, 300)
SESSIONS = ((34200, 41400), (46800, 53820))
FEATURES = ["queue_1", "depth_5", "depth_10", "microprice_bps",
            "book_ofi_30", "trade_pressure_30", "trade_pressure_60",
            "trade_count_pressure_30", "large_trade_pressure_30",
            "add_pressure_30", "cancel_pressure_30", "net_resting_flow_30",
            "cancel_ratio_60", "momentum_30", "momentum_60", "momentum_180",
            "relative_momentum_60", "vwap_gap_60", "spread_bps", "volatility_60"]


def seconds(time):
    x = np.asarray(time, dtype=np.int64)
    return (x // 10000000) * 3600 + (x // 100000 % 100) * 60 + (x // 1000 % 100) + (x % 1000) / 1000


def continuous(t):
    return ((t >= 34200) & (t < 41400)) | ((t >= 46800) & (t < 53820))


def phase(t):
    return np.select([t < 34200, continuous(t), (t >= 41400) & (t < 46800),
                      (t >= 53820) & (t <= 54000), t >= 54300],
                     ["opening", "continuous", "lunch", "closing", "after_hours"], "other")


def hash_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path, columns=None):
    return pq.read_table(path, columns=columns, use_threads=False).to_pandas()


def roll(g, col, n, how="sum"):
    return getattr(g[col].rolling(n, min_periods=n), how)()


def main(data_dir):
    for d in ("cache", "results", "figures"):
        (ROOT / d).mkdir(exist_ok=True)
    audit = {"data_date": "2026-09-23", "analysis_date": "2026-10-09", "files": {}}
    for prefix in ("snp", "exe", "ord"):
        path = data_dir / f"{prefix}_20260923.parquet"
        f = pq.ParquetFile(path)
        audit["files"][prefix] = {"path": os.path.relpath(path.resolve(), ROOT.parent), "bytes": path.stat().st_size,
            "rows": f.metadata.num_rows, "sha256": hash_file(path),
            "schema": {x.name: str(x.type) for x in f.schema_arrow}}

    print("Reading snapshots", flush=True)
    s = read(data_dir / "snp_20260923.parquet")
    s["sec"] = seconds(s.Time)
    s["phase"] = phase(s.sec)
    snap_symbols = set(s.Symbol)
    audit["snapshot_time_subseconds"] = sorted((s.Time % 1000).unique().tolist())
    audit["snapshot_duplicate_symbol_time"] = int(s.duplicated(["Symbol", "Time"]).sum())
    audit["snapshot_null_cells"] = int(s.isna().sum().sum())
    all_last = s.sort_values("sec").groupby("Symbol").tail(1).set_index("Symbol")
    sc = s[continuous(s.sec)].copy()
    for side in ("Bid", "Ask"):
        for i in range(1, 11):
            sc[f"{side}Price{i}"] = np.rint(sc[f"{side}Price{i}"] * 100).astype("int32")
    sc["bid"] = sc.BidPrice1 / 100
    sc["ask"] = sc.AskPrice1 / 100
    sc["mid"] = (sc.bid + sc.ask) / 2
    sc["spread_bps"] = (sc.ask - sc.bid) / sc.mid * 10000
    sc["valid_quote"] = (sc.bid > 0) & (sc.ask > sc.bid) & (sc.BidVolume1 > 0) & (sc.AskVolume1 > 0)
    audit["continuous_snapshot_invalid_quotes"] = int((~sc.valid_quote).sum())
    audit["continuous_snapshot_rows"] = len(sc)
    audit["crossed_quotes"] = int(((sc.bid > sc.ask) & (sc.ask > 0)).sum())
    audit["locked_quotes"] = int(((sc.bid == sc.ask) & (sc.bid > 0)).sum())
    # Conservative availability: a snapshot labelled second s is used from s+1.
    sc["available"] = sc.sec + 1
    for k in (1, 5, 10):
        b = sc[[f"BidVolume{i}" for i in range(1, k+1)]].sum(axis=1)
        a = sc[[f"AskVolume{i}" for i in range(1, k+1)]].sum(axis=1)
        sc["queue_1" if k == 1 else f"depth_{k}"] = (b-a)/(b+a).replace(0, np.nan)
    sc["microprice_bps"] = sc.queue_1 * sc.spread_bps / 2
    # Walk up to ten displayed levels for a 1,000-share IOC size. This is a
    # snapshot liquidity estimate, with no queue-fill or impact guarantee.
    for side,output in (("Bid","bid_vwap_1000"),("Ask","ask_vwap_1000")):
        px=sc[[f"{side}Price{i}" for i in range(1,11)]].to_numpy()/100
        qty=sc[[f"{side}Volume{i}" for i in range(1,11)]].to_numpy()
        qty=np.where(px>0,qty,0)
        ahead=np.cumsum(qty,axis=1)-qty
        take=np.minimum(qty,np.maximum(1000-ahead,0))
        sc[output]=np.where(take.sum(axis=1)==1000,(take*px).sum(axis=1)/1000,np.nan)
    snapshot_stats = sc.groupby("Symbol").agg(snapshot_count=("sec", "size"),
        median_spread_bps=("spread_bps", "median"), median_bid1_qty=("BidVolume1", "median"),
        median_ask1_qty=("AskVolume1", "median"), valid_quote_fraction=("valid_quote", "mean"))
    price_path = sc[sc.valid_quote].copy()
    price_path["minute"] = (price_path.sec // 60).astype(int)
    path = price_path.groupby(["Symbol", "minute"]).agg(mid=("mid", "last"), preclose=("PreClose", "last"),
        spread_bps=("spread_bps", "median"), bid1_qty=("BidVolume1", "median"), ask1_qty=("AskVolume1", "median"))
    path.to_csv(ROOT / "results/minute_quotes.csv")

    print("Reading trades", flush=True)
    tr = read(data_dir / "exe_20260923.parquet")
    tr["sec"] = seconds(tr.Time)
    tr["phase"] = phase(tr.sec)
    tr["fen"] = np.rint(tr.Price * 100).astype("int64")
    tr["turnover_fen"] = tr.fen * tr.Volume.astype("int64")
    audit["trade_flags"] = {str(k): int(v) for k,v in tr.BSFlag.value_counts().items()}
    audit["trade_null_cells"] = int(tr.isna().sum().sum())
    audit["trade_nonpositive_price_or_volume"] = int(((tr.fen <= 0) | (tr.Volume <= 0)).sum())
    audit["symbol_sets_equal"] = snap_symbols == set(tr.Symbol)
    phase_table = tr.groupby("phase").agg(trades=("Volume", "size"), volume=("Volume", "sum"), turnover_fen=("turnover_fen", "sum"))
    phase_table.to_csv(ROOT / "results/trade_phases.csv")
    auction = tr[tr.Channel != 2301].groupby("Symbol").agg(volume=("Volume", "sum"), turnover_fen=("turnover_fen", "sum"))
    auction["volume_diff_vs_snapshot"] = auction.volume - all_last.AccVolume
    auction["turnover_fen_diff_vs_snapshot"] = auction.turnover_fen - all_last.AccTurnover * 100
    auction.to_csv(ROOT / "results/daily_reconciliation.csv")
    audit["auction_volume_reconciliation_max_abs"] = int(auction.volume_diff_vs_snapshot.abs().max())
    audit["auction_amount_reconciliation_max_abs_fen"] = int(auction.turnover_fen_diff_vs_snapshot.abs().max())
    after = tr[tr.Channel == 2301].groupby("Symbol").Volume.sum().reindex(all_last.index, fill_value=0)
    audit["after_volume_reconciliation_max_abs"] = int((after - all_last.AfterVolume).abs().max())
    tc = tr[continuous(tr.sec) & (tr.Channel != 2301)].copy()
    audit["continuous_trade_direction_known_fraction"] = float(tc.BSFlag.isin([66,83]).mean())
    tc["sign"] = np.select([tc.BSFlag == 66, tc.BSFlag == 83], [1,-1], 0)
    # Cross-check aggressor flags against larger original order identifier.
    known = tc.sign != 0
    audit["direction_vs_newer_order_id_agreement"] = float((np.sign(tc.loc[known,"BidOrder"]-tc.loc[known,"AskOrder"]) == tc.loc[known,"sign"]).mean())
    # Large trade cutoffs are fitted exclusively on morning prints.
    large_cut = tc[tc.sec < 41400].groupby("Symbol").Volume.quantile(.9)
    large_cut.to_csv(ROOT / "results/morning_large_trade_cutoffs.csv")
    tc["bucket"] = (np.floor(tc.sec / 5).astype("int32") + 1) * 5
    tc["signed_qty"] = tc.sign * tc.Volume
    tc["signed_count"] = tc.sign
    tc["large_signed_qty"] = tc.signed_qty.where(tc.Volume >= tc.Symbol.map(large_cut), 0)
    aggtr = tc.groupby(["Symbol", "bucket"]).agg(trade_qty=("Volume", "sum"), trade_signed=("signed_qty", "sum"),
        trade_count=("Volume", "size"), trade_count_signed=("signed_count", "sum"),
        large_signed=("large_signed_qty", "sum"), trade_amount_fen=("turnover_fen", "sum"))
    tc["minute"] = (tc.sec // 60).astype("int32")
    minute_tr = tc.groupby(["Symbol", "minute"]).agg(volume=("Volume", "sum"),
        turnover_fen=("turnover_fen", "sum"), trade_count=("Volume", "size"), signed_qty=("signed_qty", "sum"))
    minute_tr.to_csv(ROOT / "results/minute_trades.csv")
    trade_stats = tc.groupby("Symbol").agg(continuous_volume=("Volume", "sum"),
        continuous_turnover_fen=("turnover_fen", "sum"), trades=("Volume", "size"),
        median_trade_shares=("Volume", "median"), p90_trade_shares=("Volume", lambda x:x.quantile(.9)))
    trseq = tr[["Channel", "BizIndex"]].copy()
    del tr, tc

    print("Reading orders / cancellation lifetimes", flush=True)
    o = read(data_dir / "ord_20260923.parquet")
    o["sec"] = seconds(o.Time)
    audit["symbol_sets_equal"] &= snap_symbols == set(o.Symbol)
    audit["order_null_cells"] = int(o.isna().sum().sum())
    audit["order_number_equals_bizindex"] = bool((o.OrderNumber == o.BizIndex).all())
    audit["combined_channel_seq_duplicates"] = int(pd.concat([trseq, o[["Channel","BizIndex"]]]).duplicated().sum())
    del trseq
    audit["order_codes"] = {f"{chr(int(k[0]))}/{chr(int(k[1]))}": int(v)
        for k,v in o.groupby(["FunctionCode","OrderKind"]).size().items()}
    adds = o[o.OrderKind == 65][["Symbol","Channel","OrderOriNo","sec","Volume"]].rename(columns={"sec":"add_sec","Volume":"add_qty"})
    dels = o[o.OrderKind == 68][["Symbol","Channel","OrderOriNo","sec","Volume"]].rename(columns={"sec":"delete_sec","Volume":"delete_qty"})
    audit["duplicate_add_identifiers"] = int(adds.duplicated(["Symbol","Channel","OrderOriNo"]).sum())
    life = dels.merge(adds, on=["Symbol","Channel","OrderOriNo"], how="left", validate="many_to_one")
    life["lifetime_sec"] = life.delete_sec-life.add_sec
    audit["unmatched_cancellation_messages"] = int(life.add_sec.isna().sum())
    audit["negative_cancel_lifetimes"] = int((life.lifetime_sec < 0).sum())
    lc = life[continuous(life.delete_sec) & continuous(life.add_sec)]
    life_stats = lc.groupby("Symbol").agg(cancel_messages=("lifetime_sec","size"),
        median_cancel_lifetime_sec=("lifetime_sec","median"), fraction_cancel_under_1s=("lifetime_sec",lambda x:(x<1).mean()),
        fraction_cancel_under_5s=("lifetime_sec",lambda x:(x<5).mean()))
    edges = [-.00001, .1, .5, 1, 3, 5, 10, 30, 60, 300, 1800, np.inf]
    hist = lc.groupby(pd.cut(lc.lifetime_sec,edges), observed=False).agg(messages=("lifetime_sec","size"), shares=("delete_qty","sum"))
    hist.to_csv(ROOT / "results/cancellation_lifetime.csv")
    audit["cancellation_lifetime_note"] = "Observed resting A-to-D, excludes fully executed/unreported arrivals; includes censored noncancelled orders only as excluded, not as zero lifetimes; wall-clock seconds."
    del adds, dels, life, lc
    oc = o[continuous(o.sec) & o.OrderKind.isin([65,68])].copy()
    oc["bucket"] = (np.floor(oc.sec/5).astype("int32")+1)*5
    for name, side, kind in (("add_buy",66,65),("add_sell",83,65),("cancel_buy",66,68),("cancel_sell",83,68)):
        oc[name] = oc.Volume.where((oc.FunctionCode==side)&(oc.OrderKind==kind),0)
    aggo = oc.groupby(["Symbol","bucket"])[["add_buy","add_sell","cancel_buy","cancel_sell"]].sum()
    order_stats = oc.groupby("Symbol").agg(resting_messages=("Volume","size"),
        add_buy=("add_buy","sum"),add_sell=("add_sell","sum"),cancel_buy=("cancel_buy","sum"),cancel_sell=("cancel_sell","sum"))
    del o, oc
    stats = snapshot_stats.join(trade_stats).join(order_stats).join(life_stats)
    stats["day_return_pct"] = (all_last.Price/all_last.PreClose - 1)*100
    stats["star"] = stats.index.astype(str).str.startswith("688")
    stats.to_csv(ROOT / "results/symbol_summary.csv")

    print("Building causal panel", flush=True)
    frames = []
    quote_cols = ["available","sec","bid","ask","mid","valid_quote","spread_bps","BidVolume1","AskVolume1",
                  "queue_1","depth_5","depth_10","microprice_bps","bid_vwap_1000","ask_vwap_1000"]
    for sym in sorted(snap_symbols):
        for session,(start,end) in enumerate(SESSIONS):
            grid = pd.DataFrame({"t":np.arange(start+5,end,5,dtype=float)})
            snaps = sc[(sc.Symbol==sym)&(sc.sec>=start)&(sc.sec<end)][quote_cols].sort_values("available")
            g = pd.merge_asof(grid, snaps, left_on="t",right_on="available",direction="backward")
            g["quote_age"] = g.t - g.sec
            good = g.valid_quote.fillna(False) & (g.quote_age <= 8)
            g.loc[~good,["mid","bid","ask"]] = np.nan
            g = g.set_index("t")
            for ag in (aggtr,aggo):
                g = g.join(ag.loc[sym] if sym in ag.index.get_level_values(0) else pd.DataFrame(),how="left")
            flowcols = list(aggtr.columns)+list(aggo.columns)
            g[flowcols] = g[flowcols].fillna(0)
            b,a = g.bid,g.ask
            bq,aq = g.BidVolume1,g.AskVolume1
            g["ofi"] = (b>=b.shift()).astype(int)*bq-(b<=b.shift()).astype(int)*bq.shift() \
                -(a<=a.shift()).astype(int)*aq+(a>=a.shift()).astype(int)*aq.shift()
            g["book_ofi_30"] = roll(g,"ofi",6)/(bq+aq).rolling(6,min_periods=6).mean().replace(0,np.nan)
            for sec in (30,60):
                n = sec//5
                tq = roll(g,"trade_qty",n).replace(0,np.nan)
                g[f"trade_pressure_{sec}"] = roll(g,"trade_signed",n)/tq
            g["trade_count_pressure_30"] = roll(g,"trade_count_signed",6)/roll(g,"trade_count",6).replace(0,np.nan)
            g["large_trade_pressure_30"] = roll(g,"large_signed",6)/roll(g,"trade_qty",6).replace(0,np.nan)
            ab,ass,cb,cs = [roll(g,c,6) for c in aggo.columns]
            g["add_pressure_30"] = (ab-ass)/(ab+ass).replace(0,np.nan)
            g["cancel_pressure_30"] = (cs-cb)/(cs+cb).replace(0,np.nan)
            g["net_resting_flow_30"] = (ab-ass-cb+cs)/(ab+ass+cb+cs).replace(0,np.nan)
            g["cancel_ratio_60"] = (roll(g,"cancel_buy",12)+roll(g,"cancel_sell",12))/ \
                (roll(g,"add_buy",12)+roll(g,"add_sell",12)).replace(0,np.nan)
            for sec in (30,60,180):
                g[f"momentum_{sec}"] = (g.mid/g.mid.shift(sec//5)-1)*10000
            vwap = roll(g,"trade_amount_fen",12)/roll(g,"trade_qty",12).replace(0,np.nan)/100
            g["vwap_gap_60"] = (g.mid/vwap-1)*10000
            g["volatility_60"] = (g.mid/g.mid.shift()-1).rolling(12,min_periods=12).std()*10000
            # Decision at t, entry quote sampled at t+5s; all exits within session.
            for h in HORIZONS:
                g[f"entry_mid"] = g.mid.shift(-1)
                g[f"entry_bid"] = g.bid.shift(-1)
                g[f"entry_ask"] = g.ask.shift(-1)
                g["entry_bid_vwap_1000"] = g.bid_vwap_1000.shift(-1).where(g.mid.shift(-1).notna())
                g["entry_ask_vwap_1000"] = g.ask_vwap_1000.shift(-1).where(g.mid.shift(-1).notna())
                g[f"entry_bid_qty"] = g.BidVolume1.shift(-1).where(g.bid.shift(-1).notna())
                g[f"entry_ask_qty"] = g.AskVolume1.shift(-1).where(g.ask.shift(-1).notna())
                for q in ("mid","bid","ask","BidVolume1","AskVolume1","bid_vwap_1000","ask_vwap_1000"):
                    g[f"exit_{q}_{h}"] = g[q].shift(-(h//5+1)).where(g.mid.shift(-(h//5+1)).notna())
                g[f"y_{h}"] = (g[f"exit_mid_{h}"]/g.entry_mid-1)*10000
            g["Symbol"] = sym
            g["session"] = session
            frames.append(g.reset_index())
    panel = pd.concat(frames,ignore_index=True).sort_values(["Symbol","t"])
    panel["relative_momentum_60"] = panel.momentum_60-panel.groupby("t").momentum_60.transform("mean")
    panel["split"] = np.select([
        (panel.t>=34500)&(panel.t<41100),
        (panel.t>=47100)&(panel.t<50100),
        (panel.t>=50700)&(panel.t<53400)], ["train","validation","test"], "excluded")
    # Labels used in each stage may not reach into another stage or auctions.
    split_end = panel.split.map({"train":41400,"validation":50400,"test":53820}).fillna(0)
    for h in HORIZONS:
        panel.loc[panel.t+5+h >= split_end, f"y_{h}"] = np.nan
    audit["panel_rows"] = len(panel)
    audit["usable_60s_by_split"] = {str(k):int(v) for k,v in panel[panel.mid.notna()&panel.y_60.notna()].groupby("split").size().items()}
    audit["features"] = FEATURES
    audit["source_mutation"] = False
    panel.replace([np.inf,-np.inf],np.nan).to_parquet(ROOT / "cache/features.parquet",index=False)
    (ROOT / "results/data_audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:audit[k] for k in ["panel_rows","usable_60s_by_split","continuous_trade_direction_known_fraction",
        "direction_vs_newer_order_id_agreement","auction_volume_reconciliation_max_abs","unmatched_cancellation_messages"]},indent=2),flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir",type=Path,default=DEFAULT_DATA)
    args = parser.parse_args()
    main(args.data_dir)
