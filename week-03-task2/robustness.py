"""Descriptive mechanism checks and preselected signal robustness."""
import json
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from build_features import ROOT
from research import rank_ic, fee


def main():
    p=pd.read_parquet(ROOT/"cache/features.parquet")
    pred=pd.read_parquet(ROOT/"cache/predictions.parquet")
    selection=json.loads((ROOT/"results/selection.json").read_text())
    name=selection["selected"];h=selection["horizon"]
    mechanisms=[]
    for split in ("train","validation","test"):
        g=p[(p.split==split)&p.mid.notna()]
        for f in ("book_ofi_30","trade_pressure_30","queue_1","depth_10"):
            mechanisms.append({"split":split,"feature":f,
                "contemporaneous_past_30s_ic":rank_ic(g[f],g.momentum_30),
                "future_60s_ic":rank_ic(g[f],g.y_60)})
    pd.DataFrame(mechanisms).to_csv(ROOT/"results/contemporaneous_vs_predictive.csv",index=False)
    g=pred[(pred.split=="test")&pred[f"y_{h}"].notna()&pred[name].notna()].copy()
    x=rankdata(g[name]);y=rankdata(g[f"y_{h}"])
    x-=x.mean();y-=y.mean()
    denom=np.linalg.norm(x)*np.linalg.norm(y)
    observed=np.dot(x,y)/denom
    groups=list(g.groupby("Symbol",sort=False).indices.values())
    rng=np.random.default_rng(20260923)
    controls=[]
    # Shared circular clock shifts preserve cross-stock shocks and serial runs.
    # This is a falsification check, not a significance claim about future days.
    for offset in rng.integers(120,420,size=200):
        xr=x.copy()
        for idx in groups:
            xr[idx]=np.roll(x[idx],int(offset))
        controls.append(float(np.dot(xr,y)/denom))
    placebo={"observed_ic":float(observed),"shared_shift_null_mean":float(np.mean(controls)),
        "null_p025":float(np.quantile(controls,.025)),"null_p975":float(np.quantile(controls,.975)),
        "one_sided_empirical_fraction":float((1+np.sum(np.asarray(controls)>=observed))/201),
        "replicates":200,"note":"Same-day circular-shift placebo; not a multiple-testing-adjusted or cross-day p-value."}
    (ROOT/"results/placebo.json").write_text(json.dumps(placebo,indent=2)+"\n")
    pd.Series(controls,name="shifted_ic").to_csv(ROOT/"results/placebo_distribution.csv",index=False)
    events=pd.read_csv(ROOT/"results/selected_test_events.csv")
    costs=[]
    for qty in (100,1000,5000):
        for commission in (.00005,.0001,.00025):
            # Mainboard 100 / STAR >=200; use appropriate valid minimum.
            size=np.where(events.Symbol.astype(str).str.startswith("688")&(qty<200),200,qty)
            sell=np.where(events.sign>0,events[f"exit_bid_{h}"],events.entry_bid)
            buy=np.where(events.sign>0,events.entry_ask,events[f"exit_ask_{h}"])
            fee_bps=np.array([fee(s*q,"sell",commission)+fee(b*q,"buy",commission) for s,b,q in zip(sell,buy,size)])/(size*events.entry_mid)*10000
            costs.append({"requested_shares":qty,"all_in_commission_bps_per_side":commission*10000,
                "mean_fee_bps":fee_bps.mean(),"net_bps_best_quote_optimistic":(events.cross_edge_bps-fee_bps).mean()})
    pd.DataFrame(costs).to_csv(ROOT/"results/cost_sensitivity.csv",index=False)
    hetero=events.groupby(events.Symbol.astype(str).str.startswith("688")).agg(
        events=("net_edge_bps","size"),mid_edge_bps=("mid_edge_bps","mean"),net_edge_bps=("net_edge_bps","mean"))
    hetero.index.name="star"
    hetero.to_csv(ROOT/"results/board_sensitivity.csv")
    print(json.dumps(placebo,indent=2),flush=True)


if __name__=="__main__":main()
