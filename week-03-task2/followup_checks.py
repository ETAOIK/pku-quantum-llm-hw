"""Post-discovery descriptive checks; all periods have already been viewed."""
import os
os.environ.setdefault("MPLCONFIGDIR","/private/tmp/week03-task2-mpl")
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from build_features import ROOT
from research import fee,block_ci


def main():
    p=pd.read_parquet(ROOT/"cache/features.parquet")
    p=p[(p.split!="excluded")&p.mid.notna()&p.y_60.notna()].copy()
    th=p[p.split=="train"].groupby("Symbol").vwap_gap_60.quantile([.1,.9]).unstack()
    p["market_relative_y"]=p.y_60-p.groupby("t").y_60.transform("mean")
    rows=[]
    for split in ("train","validation","test"):
        g=p[p.split==split]
        for label,condition in [("low_gap",g.vwap_gap_60<=g.Symbol.map(th[.1])),
                                ("high_gap",g.vwap_gap_60>=g.Symbol.map(th[.9]))]:
            e=g[condition];ci=block_ci(e.y_60,e.t)
            rows.append(dict(split=split,condition=label,n=len(e),future_mid_bps=e.y_60.mean(),
                market_relative_bps=e.market_relative_y.mean(),ci_low=ci[0],ci_high=ci[1]))
    pd.DataFrame(rows).to_csv(ROOT/"results/followup_vwap_extremes.csv",index=False)
    rows=[]
    for split in ("train","validation","test"):
        g=p[p.split==split]
        for label,condition in [("down_thick_bid",(g.momentum_30<0)&(g.queue_1>0)),
                               ("down_thin_bid",(g.momentum_30<0)&(g.queue_1<0)),
                               ("up_thick_bid",(g.momentum_30>0)&(g.queue_1>0)),
                               ("up_thin_bid",(g.momentum_30>0)&(g.queue_1<0))]:
            e=g[condition]
            rows.append(dict(split=split,condition=label,n=len(e),future_mid_bps=e.y_60.mean(),
                             market_relative_bps=e.market_relative_y.mean()))
    pd.DataFrame(rows).to_csv(ROOT/"results/followup_queue_conditions.csv",index=False)

    pred=pd.read_parquet(ROOT/"cache/predictions.parquet")[["Symbol","t","ridge_all","hgb_all"]]
    p=p.merge(pred,on=["Symbol","t"],how="left")
    plans=[];summaries=[]
    for split in ("validation","test"):
        # A fixed, mandatory 1,000-share buy every two clock minutes; deadline
        # 60 seconds after delayed entry. No selection of extreme-score orders.
        g=p[(p.split==split)&(p.t%120==0)].copy()
        for name,wait in [("always_immediate",pd.Series(False,index=g.index)),
                          ("always_wait",pd.Series(True,index=g.index)),
                          ("gap_above_zero_wait",g.vwap_gap_60>0),
                          ("relative_outperformance_wait",g.relative_momentum_60>0),
                          ("ridge_negative_wait",g.ridge_all<0),
                          ("hgb_negative_wait",g.hgb_all<0)]:
            now=g.entry_ask_vwap_1000
            delayed=g.exit_ask_vwap_1000_60
            policy=pd.Series(np.where(wait,delayed,now),index=g.index)
            valid=now.notna()&policy.notna()
            baseline_cost=now*1000+now.map(lambda x:fee(x*1000,"buy"))
            policy_cost=policy*1000+policy.map(lambda x:fee(x*1000,"buy") if np.isfinite(x) else np.nan)
            savings=baseline_cost-policy_cost
            normalized=savings/(g.entry_mid*1000)*10000
            ci=block_ci(normalized[valid],g.loc[valid,"t"])
            summaries.append(dict(split=split,policy=name,planned_lots=len(g),completed_pairs=int(valid.sum()),
                wait_fraction=wait.mean(),saving_cny=savings.sum(),mean_lot_saving_bps=normalized[valid].mean(),
                notional_weighted_saving_bps=savings.sum()/(g.loc[valid,"entry_mid"].sum()*1000)*10000,
                ci_low=ci[0],ci_high=ci[1],clock_blocks=ci[2]))
            plans.append(pd.DataFrame(dict(split=split,policy=name,Symbol=g.Symbol,t=g.t,wait=wait,
                immediate_price=now,policy_price=policy,saving_cny=savings,saving_bps=normalized)))
    summary=pd.DataFrame(summaries)
    summary.to_csv(ROOT/"results/followup_fixed_buy_plan.csv",index=False)
    pd.concat(plans).to_csv(ROOT/"results/followup_fixed_buy_orders.csv",index=False)
    plt.rcParams.update({"font.family":["Arial","Helvetica","DejaVu Sans"],"font.size":12,
        "axes.spines.top":False,"axes.spines.right":False,"legend.frameon":False,"svg.fonttype":"none"})
    fig,axes=plt.subplots(1,2,figsize=(14,5.8))
    d=pd.read_csv(ROOT/"results/followup_vwap_extremes.csv")
    for offset,condition,color,label in [(-.18,"low_gap","#0F4D92","Below morning 10th percentile"),
                                          (.18,"high_gap","#B64342","Above morning 90th percentile")]:
        e=d[d.condition==condition]
        axes[0].bar(np.arange(3)+offset,e.future_mid_bps,width=.35,color=color,label=label)
    axes[0].set_xticks(range(3),["Morning","13:05-13:55","14:05-14:50"])
    axes[0].set(title="A. Recent VWAP deviation and next-minute pullback",ylabel="Conditional future mid return (bps)")
    axes[0].axhline(0,color="#767676",lw=.8);axes[0].legend(fontsize=9)
    names=["always_wait","gap_above_zero_wait","ridge_negative_wait","hgb_negative_wait"]
    for offset,split,color in [(-.18,"validation","#42949E"),(.18,"test","#0F4D92")]:
        e=summary[summary.split==split].set_index("policy").loc[names]
        axes[1].bar(np.arange(4)+offset,e.mean_lot_saving_bps,width=.35,color=color,label=split)
        axes[1].errorbar(np.arange(4)+offset,e.mean_lot_saving_bps,
            yerr=np.array([e.mean_lot_saving_bps-e.ci_low,e.ci_high-e.mean_lot_saving_bps]),fmt="none",ecolor="#272727",capsize=3)
    axes[1].set_xticks(range(4),["Always wait","VWAP rule","Ridge rule","HGB rule"])
    axes[1].set(title="B. Complete fixed buy schedule vs immediate execution",ylabel="Mean planned-lot saving incl. buy fee (bps)")
    axes[1].axhline(0,color="#767676",lw=.8);axes[1].legend(fontsize=10)
    fig.suptitle("Post-discovery exploration on an already viewed day; fixed historical quotes, no market response",fontsize=13)
    fig.tight_layout(pad=1.8)
    for ext in ("png","pdf","svg"):
        fig.savefig(ROOT/f"figures/10-followup-reversion-and-execution.{ext}",dpi=300,bbox_inches="tight")
    plt.close(fig)
    print(summary.round(5).to_string(index=False))


if __name__=="__main__":main()
