"""Round 2: fixed ML factor comparison; no 2025 performance evaluation."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from run import FACTORS, HERE, PRODUCTS, evaluate, load_panel, passes, thresholds

CONTEXT = ["intraday", "prior_mom5", "prior_mom20", "prior_vol20",
           "volume_ratio", "oi_change", "close_location", "range_pct"]
PRODUCT_COLUMNS = [f"product_{p}" for p in PRODUCTS]
SETS = {"gap": FACTORS, "context": CONTEXT, "combined": FACTORS+CONTEXT}


def context_features(bars):
    o, h, l, c = (bars[k] for k in ("open", "high", "low", "close"))
    price = bars[["open","high","low","close"]]
    valid = ((price>0).all(axis=1) & (h>=price.max(axis=1)) & (l<=price.min(axis=1)))
    o, h, l, c = (series.where(valid) for series in (o,h,l,c))
    prior = c.shift(1)
    span = h-l
    return pd.DataFrame({
        "intraday": np.log(c/o),
        "prior_mom5": np.log(prior/c.shift(6)),
        "prior_mom20": np.log(prior/c.shift(21)),
        "prior_vol20": np.log(c/c.shift(1)).rolling(20).std().shift(1),
        "volume_ratio": bars.volume.where(valid)/bars.volume.where(valid).rolling(20).mean().shift(1),
        "oi_change": bars.hold.where(valid)/bars.hold.where(valid).shift(1).replace(0,np.nan)-1,
        "close_location": (2*(c-l)/span.replace(0,np.nan)-1).where(span!=0,0),
        "range_pct": span/c,
    }).replace([np.inf,-np.inf],np.nan)


def dataset(plan):
    base = json.loads((HERE/"plan.json").read_text())
    # Truncate before feature/label creation: never create a 2025 evaluation row.
    base["holdout"][1] = plan["comparison_period"][1]
    panel, calendar, audit = load_panel(base)
    features = []
    for path in sorted((HERE/"data").glob("*.json")):
        bars = pd.DataFrame(json.loads(path.read_text())).rename(columns={
            "d":"date","o":"open","h":"high","l":"low","c":"close","v":"volume","p":"hold"})
        bars.date = pd.to_datetime(bars.date)
        bars = bars[bars.date<=plan["comparison_period"][1]].sort_values("date").reset_index(drop=True)
        for key in ("open","high","low","close","volume","hold"):
            bars[key] = pd.to_numeric(bars[key])
        f = context_features(bars)
        f["date"], f["symbol"] = bars.date, path.stem
        features.append(f)
    panel = panel.merge(pd.concat(features),on=["date","symbol"],validate="one_to_one")
    before = len(panel)
    panel = panel[np.isfinite(panel[CONTEXT]).all(axis=1) & panel.target.notna()].copy()
    for product in PRODUCTS:
        panel[f"product_{product}"] = (panel["product"]==product).astype(float)
    panel = panel.sort_values(["entry_date","product"]).reset_index(drop=True)
    audit["context_or_target_removed"] = before-len(panel)
    audit["common_cohort"] = len(panel)
    assert panel.entry_date.max() < pd.Timestamp("2025-01-01")
    return panel,calendar,audit


def estimator(family, plan):
    params = plan["models"][family]
    if family=="ridge":
        return make_pipeline(StandardScaler(),Ridge(**params))
    if family=="elastic_net":
        return make_pipeline(StandardScaler(),ElasticNet(**params,random_state=plan["seed"]))
    if family=="random_forest":
        return RandomForestRegressor(**params,random_state=plan["seed"])
    return HistGradientBoostingRegressor(**params,random_state=plan["seed"])


def time_fold(panel, start, end):
    score = panel[(panel.entry_date>=start)&(panel.entry_date<=end)]
    if score.empty:
        raise ValueError("Empty score fold")
    fit = panel[panel.entry_date < score.date.min()]
    assert fit.entry_date.max() < score.date.min()
    return fit,score


def fit_predict(panel, family, feature_set, plan):
    columns = SETS[feature_set]+PRODUCT_COLUMNS
    oof = pd.Series(np.nan,index=panel.index)
    folds, importance = [], []
    for start,end in plan["oof_folds"]:
        fit,score = time_fold(panel,start,end)
        model = estimator(family,plan)
        model.fit(fit[columns],fit.target*10000)
        pred = model.predict(score[columns])
        oof.loc[score.index] = pred
        folds.append({"start":start,"end":end,"fit_samples":len(fit),"score_samples":len(score),
                      "fit_label_max":str(fit.entry_date.max().date()),
                      "score_signal_min":str(score.date.min().date())})
        baseline_mse = np.mean((pred-score.target.to_numpy()*10000)**2)
        rng = np.random.default_rng(plan["seed"])
        for group,names in (("gap",FACTORS),("context",CONTEXT)):
            names = [name for name in names if name in columns]
            if not names:
                continue
            shuffled = score[columns].copy()
            # Joint permutation within product keeps product identity and group correlations.
            for _, rows in score.groupby("product"):
                indices = rng.permutation(rows.index)
                shuffled.loc[rows.index,names] = score.loc[indices,names].to_numpy()
            mse = np.mean((model.predict(shuffled)-score.target.to_numpy()*10000)**2)
            importance.append({"fold":start,"group":group,"delta_mse_bps2":float(mse-baseline_mse),"samples":len(score)})
    fit,comparison = time_fold(panel,*plan["comparison_period"])
    final = estimator(family,plan)
    final.fit(fit[columns],fit.target*10000)
    comparison_score = pd.Series(final.predict(comparison[columns]),index=comparison.index)
    coefficients = []
    if family in ("ridge","elastic_net"):
        for name,value in zip(columns,final[-1].coef_):
            coefficients.append({"feature":name,"standardized_coefficient_bps":float(value)})
    return oof,comparison_score,folds,importance,coefficients


def compare_scores(frame, calendar, candidates, limits, cost, stage):
    metrics, positions, daily_returns = [], {}, {}
    for candidate in candidates:
        m,daily,obs = evaluate(frame,calendar,candidate,limits[candidate],cost)
        active = obs.position.ne(0) & frame.gap_raw.ne(0)
        m.update({"stage":stage,"momentum_agreement":float((obs.loc[active,"position"]==np.sign(frame.loc[active,"gap_raw"])).mean())})
        metrics.append(m)
        positions[candidate] = obs.position
        daily_returns[candidate] = daily.net
    return metrics,pd.DataFrame(positions),pd.DataFrame(daily_returns)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=HERE/"round-02")
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("Output exists; choose a new reproduction path")
    plan = json.loads((HERE/"plan-ml.json").read_text())
    panel,calendar,audit = dataset(plan)
    candidates = [f"{family}__{group}" for family in plan["models"] for group in plan["feature_sets"]]
    assert len(candidates)==plan["new_candidates"]==12
    oof = panel[(panel.entry_date>=plan["oof_folds"][0][0]) & (panel.entry_date<=plan["oof_folds"][-1][1])].copy()
    comparison = panel[(panel.entry_date>=plan["comparison_period"][0]) & (panel.entry_date<=plan["comparison_period"][1])].copy()
    folds, importance, coefficients = {}, [], []
    with threadpool_limits(limits=1):
        for candidate in candidates:
            family,group = candidate.split("__")
            pred,comp,folds[candidate],imp,coef = fit_predict(panel,family,group,plan)
            oof[candidate],comparison[candidate] = pred.loc[oof.index],comp.loc[comparison.index]
            importance.extend({"candidate":candidate,**row} for row in imp)
            coefficients.extend({"candidate":candidate,**row} for row in coef)
            print(candidate,"OOF",len(oof),"comparison",len(comparison),flush=True)
    signals = plan["baselines"]+candidates
    assert oof[signals].notna().all().all() and comparison[signals].notna().all().all()
    limits = {name:thresholds(oof,name) for name in signals}
    oof_days = calendar[(calendar>=plan["oof_folds"][0][0])&(calendar<=plan["oof_folds"][-1][1])]
    comp_days = calendar[(calendar>=plan["comparison_period"][0])&(calendar<=plan["comparison_period"][1])]
    training,_,_ = compare_scores(oof,oof_days,signals,limits,5,"training_oof")
    eligible = sorted([m for m in training if m["factor"] in candidates and passes(m,100)],key=lambda m:(-m["sharpe"],m["factor"]))
    selected = eligible[0]["factor"] if eligible else None
    # Selection is complete before producing comparison-period metrics.
    compared,positions,daily = compare_scores(comparison,comp_days,signals,limits,5,"reused_validation")
    cost_metrics = []
    for cost in plan["roundtrip_cost_bps"]:
        if cost!=5:
            rows,_,_ = compare_scores(comparison,comp_days,signals,limits,cost,"reused_validation")
            cost_metrics.extend(rows)
    metrics = training+compared+cost_metrics
    args.output.mkdir(parents=True)
    pd.DataFrame([{k:v for k,v in m.items() if k!="ic_by_product"} for m in metrics]).to_csv(args.output/"metrics.csv",index=False)
    pd.DataFrame(importance).to_csv(args.output/"oof-group-importance.csv",index=False)
    pd.DataFrame(coefficients).to_csv(args.output/"linear-coefficients.csv",index=False)
    columns = ["date","entry_date","symbol","product","target"]+signals
    oof[columns].to_csv(args.output/"oof-scores.csv",index=False)
    comparison[columns].to_csv(args.output/"comparison-scores.csv",index=False)
    daily.to_csv(args.output/"comparison-daily.csv",index_label="entry_date")
    positions.index = pd.MultiIndex.from_frame(comparison[["entry_date","product"]])
    positions.to_csv(args.output/"comparison-positions.csv")
    # Average within-product rank correlations; avoid spurious product-level offsets.
    correlations = [rows[signals].rank().corr() for _,rows in comparison.groupby("product")]
    (sum(correlations)/len(correlations)).to_csv(args.output/"score-rank-correlation.csv")
    overlap = pd.DataFrame(index=signals,columns=signals,dtype=float)
    for a in signals:
        for b in signals:
            union = positions[a].ne(0)|positions[b].ne(0)
            overlap.loc[a,b] = float(((positions[a]==positions[b]) & positions[a].ne(0))[union].mean())
    overlap.to_csv(args.output/"position-overlap.csv")
    by_product = []
    for name in signals:
        m = next(m for m in compared if m["factor"]==name)
        for product,rows in comparison.groupby("product"):
            pos = positions[name].xs(product,level="product")
            values = pos.to_numpy()*rows.target.to_numpy()-pos.abs().to_numpy()*0.0005
            by_product.append({"candidate":name,"product":product,"rank_ic":m["ic_by_product"][product],
                               "trades":int(pos.ne(0).sum()),"net_sum":float(values.sum())})
    pd.DataFrame(by_product).to_csv(args.output/"comparison-by-product.csv",index=False)
    chosen = next((m for m in compared if m["factor"]==selected),None)
    summary = {"round":2,"rounds_used":2,"max_rounds":4,"new_candidates":12,"baselines":plan["baselines"],
               "selected_on_training_oof":selected,"oof_eligible":len(eligible),
               "selected_comparison":chosen,"comparison_passed":bool(chosen and passes(chosen,50)),
               "independently_qualified":False,"holdout_opened":False,
               "comparison_status":"exploratory_reused_2023_2024", "thresholds":limits,
               "audit":audit,"oof_samples":len(oof),"comparison_samples":len(comparison),"folds":folds,
               "versions":{"numpy":np.__version__,"pandas":pd.__version__,"sklearn":sklearn.__version__},
               "inputs_sha256":{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in
                                 ("plan-ml.json","plan.json","data-lock.json","factors.py","run.py","ml.py")},
               "artifacts_sha256":{file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(args.output.glob("*.csv"))}}
    (args.output/"summary.json").write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n")
    print(json.dumps({key:summary[key] for key in ("new_candidates","selected_on_training_oof","comparison_passed","holdout_opened")}))


if __name__=="__main__":
    main()
