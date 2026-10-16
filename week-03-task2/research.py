"""Frozen candidate comparison, same-day holdout, costs and inventory study."""
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from build_features import ROOT, FEATURES, HORIZONS

SEED = 20260923
COMMISSION = .0001  # Assumed all-in brokerage, including exchange regulatory fees.
TRANSFER = .00001
STAMP = .0005
QUANTITY = 1000


def fee(notional, side, commission=COMMISSION):
    """Assumed minimum CNY 5 per executed order; no duplicate regulatory fees."""
    return max(5.,notional*commission)+notional*(TRANSFER+(STAMP if side=="sell" else 0))


def rank_ic(x,y):
    good = np.isfinite(x)&np.isfinite(y)
    if good.sum()<30 or np.nanstd(np.asarray(x)[good])==0:
        return np.nan
    return float(spearmanr(np.asarray(x)[good],np.asarray(y)[good]).statistic)


def block_ci(values, times, reps=1000):
    """Resample common five-minute clock blocks, preserving within-block dependence."""
    g = pd.DataFrame({"value":values,"block":np.asarray(times)//300}).dropna()
    b = g.groupby("block").value.agg(["sum","count"])
    if len(b)<2:
        return (np.nan,np.nan,len(b))
    rng = np.random.default_rng(SEED)
    ids = rng.integers(0,len(b),(reps,len(b)))
    sims = b["sum"].to_numpy()[ids].sum(axis=1)/b["count"].to_numpy()[ids].sum(axis=1)
    return (*np.quantile(sims,[.025,.975]),len(b))


def nonoverlap(df,horizon):
    pieces=[]
    for _,g in df.sort_values("t").groupby("Symbol"):
        last=-np.inf
        for idx,t in zip(g.index,g.t):
            if t>=last:
                pieces.append(idx)
                last=t+5+horizon
    return df.loc[pieces]


def tail_stats(df,h):
    g = df[(df.score<=df.low)|(df.score>=df.high)].copy()
    g = nonoverlap(g,h)
    if len(g)==0:
        return {"n":0,"mid_edge_bps":np.nan,"cross_edge_bps":np.nan,"net_edge_bps":np.nan}
    sign=np.where(g.score>=g.high,1.,-1.)
    mid=sign*g[f"y_{h}"].to_numpy()
    # Sell-first and buy-first pairs are diagnostic; only inventory episodes below
    # enforce the initial sellable-share budget.
    sell=np.where(sign>0,g[f"exit_bid_{h}"],g.entry_bid)
    buy=np.where(sign>0,g.entry_ask,g[f"exit_ask_{h}"])
    ref=g.entry_mid.to_numpy()
    crossing=(sell-buy)/ref*10000
    costs=np.array([fee(s*QUANTITY,"sell")+fee(b*QUANTITY,"buy") for s,b in zip(sell,buy)])/(ref*QUANTITY)*10000
    net=crossing-costs
    ci=block_ci(net,g.t)
    g["sign"]=sign
    g["mid_edge_bps"]=mid
    g["cross_edge_bps"]=crossing
    g["fee_bps"]=costs
    g["net_edge_bps"]=net
    return {"n":len(g),"mid_edge_bps":float(mid.mean()),"cross_edge_bps":float(crossing.mean()),
            "fee_bps":float(costs.mean()),"net_edge_bps":float(net.mean()),"net_ci_low":ci[0],"net_ci_high":ci[1],
            "clock_blocks":ci[2],"win_fraction":float((net>0).mean()),"events":g}


def standardize(panel,feature):
    train=panel[panel.split=="train"]
    stats=train.groupby("Symbol")[feature].agg(["mean","std"])
    mean=panel.Symbol.map(stats["mean"])
    std=panel.Symbol.map(stats["std"]).replace(0,np.nan)
    return ((panel[feature]-mean)/std).clip(-10,10)


def write_cash_ledger(episodes):
    """Verify an explicit shared CNY 100,000 cash buffer for each scenario."""
    ledger=[];summaries=[]
    for (candidate,split,policy),g in episodes.groupby(["candidate","split","policy"]):
        events=[]
        for r in g.itertuples():
            sell=r.sell_price*r.shares
            events.append((r.sell_t,"sell",r.Symbol,sell-fee(sell,"sell")))
            if r.completed:
                buy=r.buy_price*r.shares
                events.append((r.buy_t,"buy",r.Symbol,-buy-fee(buy,"buy")))
        cash=100000.;minimum=cash
        for t,side,symbol,flow in sorted(events):
            cash+=flow;minimum=min(minimum,cash)
            ledger.append(dict(candidate=candidate,split=split,policy=policy,t=t,side=side,
                               Symbol=symbol,cash_delta=flow,cash_after=cash))
        summaries.append(dict(candidate=candidate,split=split,policy=policy,initial_cash=100000,
                              minimum_cash=minimum,ending_cash=cash,incremental_pnl=cash-100000))
    pd.DataFrame(ledger).to_csv(ROOT/"results/inventory_cash_ledger.csv",index=False)
    pd.DataFrame(summaries).to_csv(ROOT/"results/inventory_cash_summary.csv",index=False)


def main():
    panel=pd.read_parquet(ROOT/"cache/features.parquet")
    panel=panel[(panel.split!="excluded")&panel.mid.notna()].copy()
    panel.reset_index(drop=True,inplace=True)
    frozen={"seed":SEED,"features":FEATURES,"horizons_seconds":HORIZONS,
            "tails":"per-symbol training 10% and 90%, fixed thereafter",
            "models":["ridge_all","ridge_price_only","hgb_all"],
            "selection":"max validation mean nonoverlapping tail net bps; no test selection",
            "inventory":"1000 pre-existing sellable shares per stock; at most one sell-buy cycle per stock",
            "initial_cash_buffer_cny":100000,
            "commission":COMMISSION,"min_commission_cny":5,"transfer":TRANSFER,"sell_stamp":STAMP,
            "quote_availability_delay_seconds":1,"entry_delay_seconds":5,"max_quote_age_seconds":8,
            "splits":{"train":"09:35-11:25","validation":"13:05-13:55","test":"14:05-14:50"}}
    (ROOT/"results/frozen_protocol.json").write_text(json.dumps(frozen,ensure_ascii=False,indent=2)+"\n")
    # Save protocol before any scores are evaluated. Direction learned on morning only.
    rows=[]
    scores={}
    calibration={}
    thresholds_by_candidate={}
    for f in FEATURES:
        z=standardize(panel,f)
        for h in HORIZONS:
            train=(panel.split=="train")&panel[f"y_{h}"].notna()&z.notna()
            ic=rank_ic(z[train],panel.loc[train,f"y_{h}"])
            direction=1 if ic>=0 else -1
            score=z*direction
            thresholds=pd.DataFrame({"Symbol":panel.Symbol[train],"score":score[train]}).groupby("Symbol").score.quantile([.1,.9]).unstack()
            fit=np.polyfit(score[train],panel.loc[train,f"y_{h}"],1)
            name=f"{f}__{h}"
            scores[name]=score
            calibration[name]=fit
            thresholds_by_candidate[name]=thresholds
            for split in ("train","validation","test"):
                g=panel[(panel.split==split)&panel[f"y_{h}"].notna()].copy()
                g["score"]=score.loc[g.index]
                g["low"]=g.Symbol.map(thresholds[.1])
                g["high"]=g.Symbol.map(thresholds[.9])
                g=g[g.score.notna()]
                ts=tail_stats(g,h)
                same_time_y=g[f"y_{h}"]-g.groupby("t")[f"y_{h}"].transform("mean")
                rows.append({"candidate":name,"feature":f,"horizon":h,"split":split,"direction":direction,
                    "ic":rank_ic(g.score,g[f"y_{h}"]),"market_demeaned_ic":rank_ic(g.score,same_time_y),
                    **{k:v for k,v in ts.items() if k!="events"}})
    print("Handcrafted candidates evaluated",flush=True)
    train=(panel.split=="train")&panel.y_60.notna()
    price_features=["momentum_30","momentum_60","momentum_180","relative_momentum_60","vwap_gap_60","spread_bps","volatility_60"]
    model_specs=[("ridge_all",FEATURES,Ridge(alpha=100)),("ridge_price_only",price_features,Ridge(alpha=100)),
                 ("hgb_all",FEATURES,HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,
                   min_samples_leaf=100,learning_rate=.05,l2_regularization=10,early_stopping=False,random_state=SEED))]
    coefficients=[]
    for name,cols,est in model_specs:
        model=make_pipeline(SimpleImputer(strategy="median"),StandardScaler(),est)
        model.fit(panel.loc[train,cols],panel.loc[train,"y_60"])
        score=pd.Series(model.predict(panel[cols]),index=panel.index)
        scores[name]=score
        calibration[name]=np.array([1.,0.])
        if isinstance(est,Ridge):
            coefficients.extend({"model":name,"feature":c,"coefficient_per_std_bps":float(w)} for c,w in zip(cols,est.coef_))
        thresholds=pd.DataFrame({"Symbol":panel.Symbol[train],"score":score[train]}).groupby("Symbol").score.quantile([.1,.9]).unstack()
        thresholds_by_candidate[name]=thresholds
        for split in ("train","validation","test"):
            g=panel[(panel.split==split)&panel.y_60.notna()].copy()
            g["score"]=score.loc[g.index]
            g["low"]=g.Symbol.map(thresholds[.1])
            g["high"]=g.Symbol.map(thresholds[.9])
            ts=tail_stats(g,60)
            yrel=g.y_60-g.groupby("t").y_60.transform("mean")
            rows.append({"candidate":name,"feature":name,"horizon":60,"split":split,"direction":1,
                         "ic":rank_ic(g.score,g.y_60),"market_demeaned_ic":rank_ic(g.score,yrel),
                         **{k:v for k,v in ts.items() if k!="events"}})
        print(name,"complete",flush=True)
    pd.DataFrame(coefficients).to_csv(ROOT/"results/model_coefficients.csv",index=False)
    metrics=pd.DataFrame(rows)
    metrics.to_csv(ROOT/"results/candidate_metrics.csv",index=False)
    validation=metrics[metrics.split=="validation"].sort_values("net_edge_bps",ascending=False)
    selected=validation.iloc[0]
    name=selected.candidate
    h=int(selected.horizon)
    fit=calibration[name]
    summary={"candidate_count":len(validation),"selected":name,"horizon":h,
        "validation_net_bps":float(selected.net_edge_bps),"validation_gate_passed":bool(selected.net_edge_bps>0 and selected.net_ci_low>0),
        "test":metrics[(metrics.candidate==name)&(metrics.split=="test")].iloc[0].to_dict()}
    (ROOT/"results/selection.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print("Selected only on validation:",name,flush=True)
    # Retain predictions for audit/reproduction, with no raw source copying.
    predictions=panel[["Symbol","t","split","mid","entry_mid","entry_bid","entry_ask","quote_age"]].copy()
    for nm in dict.fromkeys([name,"queue_1__60","book_ofi_30__60","trade_pressure_30__60","ridge_all","ridge_price_only","hgb_all"]):
        predictions[nm]=scores[nm]
    for hh in HORIZONS:
        predictions[f"y_{hh}"]=panel[f"y_{hh}"]
    predictions.to_parquet(ROOT/"cache/predictions.parquet",index=False)

    # Deciles use morning edges, not quantiles estimated on test outcomes/features.
    deciles=[]
    for nm in dict.fromkeys([name,"queue_1__60","book_ofi_30__60","trade_pressure_30__60","ridge_all","ridge_price_only","hgb_all"]):
        hh=h if nm==name else 60
        score=scores[nm]
        for split in ("validation","test"):
            g=panel[(panel.split==split)&panel[f"y_{hh}"].notna()].copy()
            g["score"]=score.loc[g.index]
            g["decile"]=np.nan
            for sym,sg in g.groupby("Symbol"):
                vals=score[(panel.Symbol==sym)&(panel.split=="train")].dropna()
                edges=vals.quantile(np.arange(.1,1,.1)).to_numpy()
                g.loc[sg.index,"decile"]=np.searchsorted(edges,sg.score,side="right")+1
            for d,dg in g.groupby("decile"):
                ci=block_ci(dg[f"y_{hh}"],dg.t)
                deciles.append({"candidate":nm,"split":split,"horizon":hh,"decile":int(d),"n":len(dg),
                    "return_bps":dg[f"y_{hh}"].mean(),"ci_low":ci[0],"ci_high":ci[1]})
    pd.DataFrame(deciles).to_csv(ROOT/"results/decile_returns.csv",index=False)

    # T+1-compatible scenario: sell existing shares once, buy back once. New buys
    # cannot replenish today's sellable inventory. Failed depth causes exclusion.
    episodes=[]
    for nm in dict.fromkeys([name,"queue_1__60","ridge_all","hgb_all"]):
        hh=h if nm==name else 60
        score=scores[nm]
        cal=calibration[nm]
        for split in ("validation","test"):
            for sym,sg in panel[(panel.split==split)&panel[f"y_{hh}"].notna()].groupby("Symbol"):
                train_score=score[(panel.Symbol==sym)&(panel.split=="train")].dropna()
                cutoff=thresholds_by_candidate[nm].loc[sym,.1]
                g=sg.copy()
                g["score"]=score.loc[g.index]
                g["forecast"]=cal[0]*g.score+cal[1]
                g=g[(g.score<=cutoff)&g.entry_bid_vwap_1000.notna()].sort_values("t")
                for policy in ("forced_diagnostic","cost_gate"):
                    eligible=g.copy()
                    if policy=="cost_gate":
                        costs=g.apply(lambda r:(fee(r.entry_bid*QUANTITY,"sell")+fee(r.entry_ask*QUANTITY,"buy"))/(r.entry_mid*QUANTITY)*10000,axis=1)
                        eligible=g[-g.forecast>costs+g.spread_bps+1.0]
                    if len(eligible)==0:
                        continue
                    row=eligible.iloc[0]
                    sell=row.entry_bid_vwap_1000
                    buy=row[f"exit_ask_vwap_1000_{hh}"]
                    completed=np.isfinite(buy)
                    gross=(sell-buy)*QUANTITY
                    cost=fee(sell*QUANTITY,"sell")+fee(buy*QUANTITY,"buy")
                    episodes.append({"candidate":nm,"split":split,"policy":policy,"Symbol":int(sym),"signal_t":row.t,
                        "sell_t":row.t+5,"buy_t":row.t+5+hh,"shares":QUANTITY,"sell_price":sell,"buy_price":buy,
                        "completed":bool(completed),"gross_cny":gross if completed else np.nan,
                        "fees_cny":cost if completed else fee(sell*QUANTITY,"sell"),
                        "net_cny":gross-cost if completed else np.nan,"notional":row.entry_mid*QUANTITY,
                        "net_bps":(gross-cost)/(row.entry_mid*QUANTITY)*10000 if completed else np.nan,
                        "predicted_mid_bps":row.forecast,"sellable_after":0,"new_shares_after":QUANTITY if completed else 0})
    ep=pd.DataFrame(episodes)
    ep.to_csv(ROOT/"results/inventory_episodes.csv",index=False)
    write_cash_ledger(ep)
    inventory=[]
    for nm in dict.fromkeys([name,"queue_1__60","ridge_all","hgb_all"]):
        for split in ("validation","test"):
            for policy in ("forced_diagnostic","cost_gate"):
                e=ep[(ep.candidate==nm)&(ep.split==split)&(ep.policy==policy)] if len(ep) else ep
                inventory.append({"candidate":nm,"split":split,"policy":policy,"cycles":len(e),
                    "unresolved_buybacks":int((~e.completed).sum()) if len(e) else 0,
                    "net_cny":float(e.net_cny.sum()) if len(e) else 0,
                    "net_bps_on_traded_notional":float(e.net_cny.sum()/e.notional.sum()*10000) if len(e) else np.nan,
                    "win_fraction":float((e.net_cny>0).mean()) if len(e) else np.nan})
    pd.DataFrame(inventory).to_csv(ROOT/"results/inventory_summary.csv",index=False)

    # Incremental execution value for orders that MUST be executed: compare now
    # versus 60s later. Same-side commission/tax largely cancels; not alpha PnL.
    execution=[]
    for nm in ["queue_1__60","ridge_all","hgb_all"]:
        score=scores[nm]
        train_scores=pd.DataFrame({"Symbol":panel.Symbol[train],"score":score[train]}).groupby("Symbol").score.quantile([.1,.9]).unstack()
        for split in ("validation","test"):
            g=panel[(panel.split==split)&panel.y_60.notna()].copy()
            g["score"]=score.loc[g.index]
            for side in ("buy","sell"):
                if side=="buy":
                    e=g[g.score>=g.Symbol.map(train_scores[.9])].copy()
                    e=e[e.entry_ask_qty>=QUANTITY]
                    e["future_depth_ok"]=e.exit_AskVolume1_60>=QUANTITY
                    e["saved_bps"]=(e.exit_ask_60-e.entry_ask)/e.entry_mid*10000
                else:
                    e=g[g.score<=g.Symbol.map(train_scores[.1])].copy()
                    e=e[e.entry_bid_qty>=QUANTITY]
                    e["future_depth_ok"]=e.exit_BidVolume1_60>=QUANTITY
                    e["saved_bps"]=(e.entry_bid-e.exit_bid_60)/e.entry_mid*10000
                e=nonoverlap(e,60)
                ci=block_ci(e.saved_bps,e.t)
                execution.append({"candidate":nm,"split":split,"side":side,"n":len(e),"saved_bps":e.saved_bps.mean(),
                    "ci_low":ci[0],"ci_high":ci[1],"clock_blocks":ci[2],"future_depth_ok_fraction":e.future_depth_ok.mean()})
    pd.DataFrame(execution).to_csv(ROOT/"results/execution_timing.csv",index=False)

    # Test candidate sensitivity: quote latency, costs and stock heterogeneity.
    g=panel[(panel.split=="test")&panel[f"y_{h}"].notna()].copy()
    g["score"]=scores[name].loc[g.index]
    ts=thresholds_by_candidate[name]
    g["low"]=g.Symbol.map(ts[.1]);g["high"]=g.Symbol.map(ts[.9])
    events=tail_stats(g,h)["events"]
    events.to_csv(ROOT/"results/selected_test_events.csv",index=False)
    events.groupby("Symbol").agg(events=("net_edge_bps","size"),mid_edge_bps=("mid_edge_bps","mean"),
        net_edge_bps=("net_edge_bps","mean")).to_csv(ROOT/"results/selected_by_symbol.csv")
    sensitivity=[]
    for delay in (5,10,20,30):
        # Both entry and exit shifted by the same extra delay; fixed decision.
        p=pd.read_parquet(ROOT/"cache/features.parquet").set_index(["Symbol","t"])
        vals=[]
        for e in events.itertuples():
            keys=[(e.Symbol,e.t+delay),(e.Symbol,e.t+delay+h)]
            if not all(k in p.index for k in keys):continue
            en,ex=[p.loc[k] for k in keys]
            if not all(np.isfinite([en.mid,en.bid,en.ask,ex.mid,ex.bid,ex.ask])):continue
            sell=ex.bid if e.sign>0 else en.bid
            buy=en.ask if e.sign>0 else ex.ask
            mid=e.sign*(ex.mid/en.mid-1)*10000
            crossing=(sell-buy)/en.mid*10000
            costs=(fee(sell*QUANTITY,"sell")+fee(buy*QUANTITY,"buy"))/(en.mid*QUANTITY)*10000
            vals.append([mid,crossing,crossing-costs])
        arr=np.array(vals)
        sensitivity.append({"entry_delay_seconds":delay,"n":len(vals),"mid_edge_bps":arr[:,0].mean(),
            "cross_edge_bps":arr[:,1].mean(),"net_edge_bps":arr[:,2].mean()})
    pd.DataFrame(sensitivity).to_csv(ROOT/"results/latency_sensitivity.csv",index=False)
    env={"python":platform.python_version()}
    for nm in ["numpy","pandas","scipy","sklearn","matplotlib","pyarrow"]:
        mod=__import__(nm);env[nm]=mod.__version__
    (ROOT/"results/environment.json").write_text(json.dumps(env,indent=2)+"\n")
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


if __name__=="__main__":
    main()
