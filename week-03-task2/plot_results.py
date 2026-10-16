"""Report figures, PNG + editable SVG + vector PDF, from saved result tables."""
import json
import os
os.environ.setdefault("MPLCONFIGDIR","/private/tmp/week03-task2-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd
from build_features import ROOT, FEATURES

BLUE="#0F4D92";TEAL="#42949E";RED="#B64342";GRAY="#767676"
plt.rcParams.update({"font.family":["Arial","Helvetica","DejaVu Sans"],"font.size":12,
    "axes.spines.top":False,"axes.spines.right":False,"axes.linewidth":1.3,"legend.frameon":False,
    "svg.fonttype":"none","pdf.fonttype":42,"figure.facecolor":"white"})


def read(name):return pd.read_csv(ROOT/"results"/name)


def clock_axis(ax):
    ticks=[570,600,630,660,690,780,810,840,870,896]
    ax.set_xticks(ticks,[f"{t//60:02}:{t%60:02}" for t in ticks],rotation=35)
    ax.axvspan(690,780,color="#eeeeee",alpha=.8)


def save(fig,name,pdf):
    fig.tight_layout(pad=1.8)
    for ext in ("png","pdf","svg"):
        fig.savefig(ROOT/f"figures/{name}.{ext}",dpi=300,bbox_inches="tight")
    pdf.savefig(fig,bbox_inches="tight")
    plt.close(fig)


def main():
    selection=json.loads((ROOT/"results/selection.json").read_text())
    metrics=read("candidate_metrics.csv")
    selected=selection["selected"]
    with PdfPages(ROOT/"figures/all-figures.pdf") as pdf:
        q=read("minute_quotes.csv");tr=read("minute_trades.csv")
        q["ret_pct"]=(q.mid/q.preclose-1)*100
        piv=q.pivot(index="minute",columns="Symbol",values="ret_pct").reindex(np.arange(570,897))
        fig,axs=plt.subplots(2,2,figsize=(14,9))
        axs[0,0].plot(piv.index,piv,color=GRAY,alpha=.13,lw=.7)
        axs[0,0].plot(piv.index,piv.mean(axis=1),color=BLUE,lw=2.3,label="50-stock equal-weight mean")
        axs[0,0].set(title="A. Price paths: one observed day",ylabel="Mid / previous close - 1 (%)")
        axs[0,0].legend(fontsize=10);clock_axis(axs[0,0])
        v=(tr.groupby("minute").turnover_fen.sum()/1e10).reindex(np.arange(570,897))
        axs[0,1].plot(v.index,v,color=BLUE,lw=1.3)
        axs[0,1].set(title="B. Continuous-auction turnover",ylabel="CNY 100 million / minute");clock_axis(axs[0,1])
        spread=q.groupby("minute").spread_bps.median().reindex(np.arange(570,897))
        axs[1,0].plot(spread.index,spread,color=TEAL,lw=1.8)
        axs[1,0].set(title="C. Median spread across stocks",ylabel="Spread (bps)");clock_axis(axs[1,0])
        axs[1,1].hist(piv.iloc[-1].dropna(),bins=15,color=BLUE,alpha=.8,edgecolor="white")
        axs[1,1].set(title="D. Returns at end of continuous auction",xlabel="Return from previous close (%)",ylabel="Stocks")
        save(fig,"01-market-overview",pdf)

        s=read("symbol_summary.csv").sort_values("median_spread_bps")
        fig,axs=plt.subplots(1,3,figsize=(16,5.8))
        order=np.arange(len(s))
        axs[0].bar(order,s.median_spread_bps,color=np.where(s.star,RED,BLUE))
        axs[0].set(title="A. Spreads vary widely by stock",xlabel="Stocks sorted by median spread",ylabel="Median spread (bps)")
        axs[0].text(.05,.93,"Blue: main board; red: STAR",transform=axs[0].transAxes,fontsize=10)
        axs[1].scatter(s.continuous_turnover_fen/100,s.median_spread_bps,c=np.where(s.star,RED,BLUE),alpha=.8)
        axs[1].set(xscale="log",title="B. Liquidity and spread",xlabel="Continuous turnover (CNY, log)",ylabel="Median spread (bps)")
        hist=read("cancellation_lifetime.csv")
        axs[2].bar(np.arange(len(hist)),hist.messages/hist.messages.sum()*100,color=TEAL)
        axs[2].set_xticks(np.arange(len(hist)),["0-.1",".1-.5",".5-1","1-3","3-5","5-10","10-30","30-60","1-5m","5-30m",">30m"],rotation=55,ha="right")
        axs[2].set(title="C. Resting A-to-D lifetime",xlabel="Seconds unless marked m",ylabel="Cancellation messages (%)")
        save(fig,"02-liquidity-and-cancellations",pdf)

        hand=metrics[(metrics.split=="test")&metrics.feature.isin(FEATURES)]
        heat=hand.pivot(index="feature",columns="horizon",values="ic").reindex(FEATURES)
        fig,ax=plt.subplots(figsize=(10,9))
        vmax=max(.1,np.nanmax(abs(heat.to_numpy())))
        im=ax.imshow(heat,aspect="auto",cmap="RdBu",vmin=-vmax,vmax=vmax)
        ax.set_xticks(range(5),["15s","30s","60s","180s","300s"])
        ax.set_yticks(range(len(heat)),heat.index)
        for i in range(len(heat)):
            for j in range(5):
                val=heat.iloc[i,j]
                ax.text(j,i,f"{val:.2f}",ha="center",va="center",color="white" if abs(val)>vmax*.55 else "#272727",fontsize=10)
        fig.colorbar(im,ax=ax,label="Spearman IC (morning-fitted direction)")
        ax.set_title("Same-day holdout: 20 features x 5 horizons\n5-second entry delay; all candidates disclosed, no test selection")
        save(fig,"03-signal-horizon-heatmap",pdf)

        d=read("decile_returns.csv")
        fig,axs=plt.subplots(1,3,figsize=(16,5.5))
        for ax,nm in zip(axs,[selected,"ridge_all","hgb_all"]):
            for split,color in [("validation",TEAL),("test",BLUE)]:
                g=d[(d.candidate==nm)&(d.split==split)].sort_values("decile")
                ax.plot(g.decile,g.return_bps,"o-",color=color,label=split,lw=1.8)
                ax.fill_between(g.decile,g.ci_low,g.ci_high,color=color,alpha=.13)
            ax.axhline(0,color=GRAY,lw=.8)
            ax.set(title=nm,xlabel="Training-defined score decile",ylabel="Future mid return (bps)",xticks=range(1,11))
            ax.legend(fontsize=10)
        fig.suptitle("Conditional price response; shaded bands resample shared 5-minute clock blocks",fontsize=14)
        save(fig,"04-decile-response",pdf)

        fig,axs=plt.subplots(1,2,figsize=(13,5.5))
        g=metrics[(metrics.candidate==selected)&metrics.split.isin(["validation","test"])]
        pos=np.arange(len(g));w=.24
        for offset,col,label,color in [(-w,"mid_edge_bps","Mid-to-mid",TEAL),(0,"cross_edge_bps","Cross bid/ask",BLUE),(w,"net_edge_bps","After assumed fees",RED)]:
            axs[0].bar(pos+offset,g[col],width=w,color=color,label=label)
        axs[0].set_xticks(pos,g.split);axs[0].axhline(0,color=GRAY,lw=1)
        axs[0].set(title=f"A. Validation-selected: {selected}",ylabel="Mean per nonoverlapping episode (bps)")
        axs[0].legend(fontsize=10)
        net=metrics[metrics.split=="validation"].net_edge_bps
        axs[1].hist(net,bins=20,color=BLUE,edgecolor="white")
        axs[1].axvline(0,color=RED,lw=2)
        axs[1].set(title="B. All 103 validation candidates",xlabel="After-fee diagnostic edge (bps)",ylabel="Candidates")
        save(fig,"05-prediction-versus-trading-cost",pdf)

        fig,axs=plt.subplots(1,2,figsize=(13,5.5))
        models=metrics[metrics.candidate.isin(["ridge_price_only","ridge_all","hgb_all"])]
        labels=["Price-only ridge","L2 + price ridge","L2 + price HGB"]
        for ax,col,title in [(axs[0],"ic","A. Prediction improves less than fit suggests"),(axs[1],"net_edge_bps","B. Better prediction still faces costs")]:
            for offset,split,color in [(-.25,"train",GRAY),(0,"validation",TEAL),(.25,"test",BLUE)]:
                g=models[models.split==split].set_index("candidate").loc[["ridge_price_only","ridge_all","hgb_all"]]
                ax.bar(np.arange(3)+offset,g[col],width=.24,color=color,label=split)
            ax.set_xticks(np.arange(3),labels,rotation=12)
            ax.set_title(title);ax.axhline(0,color=GRAY,lw=.8);ax.legend(fontsize=10)
        axs[0].set_ylabel("Spearman IC");axs[1].set_ylabel("Mean net diagnostic edge (bps)")
        save(fig,"06-model-comparison",pdf)

        fig,axs=plt.subplots(1,2,figsize=(13,5.5))
        lat=read("latency_sensitivity.csv")
        for col,color,label in [("mid_edge_bps",TEAL,"Mid-to-mid"),("cross_edge_bps",BLUE,"Cross spread"),("net_edge_bps",RED,"After fees")]:
            axs[0].plot(lat.entry_delay_seconds,lat[col],"o-",color=color,label=label)
        axs[0].axhline(0,color=GRAY,lw=.8);axs[0].legend(fontsize=10)
        axs[0].set(title="A. Selected signal: entry delay",xlabel="Delay after decision (seconds)",ylabel="Mean episode edge (bps)")
        cost=read("cost_sensitivity.csv")
        for qty,color in [(100,RED),(1000,BLUE),(5000,TEAL)]:
            cg=cost[cost.requested_shares==qty]
            axs[1].plot(cg.all_in_commission_bps_per_side,cg.net_bps_best_quote_optimistic,"o-",color=color,label=f"{qty:,} shares")
        axs[1].axhline(0,color=GRAY,lw=.8);axs[1].legend(fontsize=10)
        axs[1].set(title="B. Fee sensitivity, optimistic best quotes",xlabel="All-in commission per side (bps)",ylabel="Net diagnostic edge (bps)")
        save(fig,"07-delay-and-fee-sensitivity",pdf)

        fig,axs=plt.subplots(1,2,figsize=(13,5.5))
        inv=read("inventory_summary.csv")
        test=inv[(inv.split=="test")&(inv.policy=="forced_diagnostic")]
        axs[0].bar(test.candidate,test.net_cny,color=RED)
        axs[0].set(title="A. One sell-buy cycle per pre-existing inventory",ylabel="Completed-cycle cash improvement (CNY)")
        axs[0].tick_params(axis="x",rotation=15);axs[0].axhline(0,color=GRAY,lw=.8)
        for i,row in enumerate(test.itertuples()):
            axs[0].text(i,row.net_cny,f"{row.cycles} attempted",ha="center",va="top",fontsize=10)
        ex=read("execution_timing.csv");ex=ex[ex.split=="test"]
        for offset,side,color in [(-.17,"buy",BLUE),(.17,"sell",TEAL)]:
            eg=ex[ex.side==side].set_index("candidate").loc[["queue_1__60","ridge_all","hgb_all"]]
            axs[1].bar(np.arange(3)+offset,eg.saved_bps,width=.32,color=color,label=side)
            errs=np.array([eg.saved_bps-eg.ci_low,eg.ci_high-eg.saved_bps])
            axs[1].errorbar(np.arange(3)+offset,eg.saved_bps,yerr=errs,fmt="none",ecolor="#272727",capsize=3)
        axs[1].set_xticks(np.arange(3),["Queue","Ridge","HGB"])
        axs[1].set(title="B. Timing value for already planned orders",ylabel="Best-quote saving vs waiting 60s (bps)")
        axs[1].axhline(0,color=GRAY,lw=.8);axs[1].legend(fontsize=10)
        fig.suptitle("Inventory cycles use 10-level 1,000-share VWAP; timing panel is a quote benchmark, not realized PnL",fontsize=12)
        save(fig,"08-inventory-and-execution-timing",pdf)

        fig,axs=plt.subplots(1,2,figsize=(13,5.5))
        mechanism=read("contemporaneous_vs_predictive.csv")
        m=mechanism[mechanism.split=="test"]
        for offset,col,color,label in [(-.18,"contemporaneous_past_30s_ic",GRAY,"Past 30s (same window)"),(.18,"future_60s_ic",BLUE,"Future 60s (+5s entry)")]:
            axs[0].bar(np.arange(len(m))+offset,m[col],width=.35,color=color,label=label)
        axs[0].set_xticks(np.arange(len(m)),["Book OFI","Trade pressure","Queue","Depth 10"],rotation=12)
        axs[0].set(title="A. Explaining a move differs from forecasting",ylabel="Spearman correlation")
        axs[0].legend(fontsize=10);axs[0].axhline(0,color=GRAY,lw=.8)
        null=read("placebo_distribution.csv");placebo=json.loads((ROOT/"results/placebo.json").read_text())
        axs[1].hist(null.shifted_ic,bins=20,color=GRAY,alpha=.75)
        axs[1].axvline(placebo["observed_ic"],color=BLUE,lw=2,label=f"Observed IC = {placebo['observed_ic']:.3f}")
        axs[1].set(title="B. Shared clock-shift falsification",xlabel="Spearman IC",ylabel="200 shifted controls")
        axs[1].legend(fontsize=10)
        save(fig,"09-mechanism-and-placebo",pdf)
    print("9 figures exported in PNG, SVG and PDF; all-figures.pdf created.")


if __name__=="__main__":main()
