"""Explain fixed round-2 results; post-hoc controls never select or tune models."""
import argparse
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR","/tmp/gap-momentum-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml import HERE, PRODUCT_COLUMNS, SETS, dataset, estimator, time_fold
from run import block_interval


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results",type=Path,default=HERE/"round-02")
    parser.add_argument("--output",type=Path,default=HERE/"comparison-02")
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("Output exists; choose a new path")
    summary = json.loads((args.results/"summary.json").read_text())
    for name,digest in summary["artifacts_sha256"].items():
        assert hashlib.sha256((args.results/name).read_bytes()).hexdigest()==digest,name
    for name,digest in summary["inputs_sha256"].items():
        assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest,name
    args.output.mkdir(parents=True)
    metrics = pd.read_csv(args.results/"metrics.csv")
    compared = metrics[(metrics.stage=="reused_validation")&(metrics.cost_bps==5)].set_index("factor")
    training = metrics[(metrics.stage=="training_oof")&(metrics.cost_bps==5)].set_index("factor")
    score = pd.read_csv(args.results/"comparison-scores.csv",parse_dates=["date","entry_date"])
    positions = pd.read_csv(args.results/"comparison-positions.csv")
    daily = pd.read_csv(args.results/"comparison-daily.csv",parse_dates=["entry_date"])
    assert positions[["entry_date","product"]].astype(str).equals(score[["entry_date","product"]].astype(str))
    # Same exposure times and costs: separates direction changes from trade filtering.
    controls = []
    for model in (summary["selected_on_training_oof"],"random_forest__combined"):
        if model is None:
            continue
        mask = positions[model].ne(0)
        for direction in ("model","raw_gap"):
            pos = positions[model].to_numpy() if direction=="model" else np.sign(score.gap_raw.to_numpy())*mask
            net = pos*score.target.to_numpy()-np.abs(pos)*0.0005
            frame = pd.DataFrame({"entry_date":score.entry_date,"net":net})
            pnl = frame.groupby("entry_date").net.sum().reindex(daily.entry_date,fill_value=0)/3
            controls.append({"mask_from":model,"direction":direction,"trades":int(np.count_nonzero(pos)),
                             "total_return":float((1+pnl).prod()-1),
                             "sharpe":float(np.sqrt(252)*pnl.mean()/pnl.std()),
                             "mean_net_bps":float(pnl.mean()*10000)})
    pd.DataFrame(controls).to_csv(args.output/"same-exposure-controls.csv",index=False)
    intervals = []
    for name in (summary["selected_on_training_oof"],"random_forest__combined","gap_volume"):
        if name:
            ci = block_interval(pd.DataFrame({"net":daily[name]}))
            intervals.append({"candidate":name,"mean_net_bps":float(daily[name].mean()*10000),
                              "block95_low":ci[0],"block95_high":ci[1]})
    pd.DataFrame(intervals).to_csv(args.output/"descriptive-intervals.csv",index=False)
    # Export readable formulas for the frozen linear fits, not additional candidates.
    plan = json.loads((HERE/"plan-ml.json").read_text())
    panel,_,_ = dataset(plan)
    fit,test = time_fold(panel,*plan["comparison_period"])
    formulas = {}
    with threadpool_limits(limits=1):
        for family in ("ridge","elastic_net"):
            for group in plan["feature_sets"]:
                name = f"{family}__{group}"
                columns = SETS[group]+PRODUCT_COLUMNS
                model = estimator(family,plan).fit(fit[columns],fit.target*10000)
                np.testing.assert_allclose(model.predict(test[columns]),score[name],atol=1e-9)
                formulas[name] = {"formula":"score_bps = intercept + sum(weight * (x - mean) / scale)",
                                  "intercept_bps":float(model[-1].intercept_),
                                  "fit_label_max":str(fit.entry_date.max().date()),
                                  "terms":[{"feature":col,"weight":float(weight),"mean":float(mean),"scale":float(scale)}
                                           for col,weight,mean,scale in zip(columns,model[-1].coef_,model[0].mean_,model[0].scale_)]}
    (args.output/"linear-formulas.json").write_text(json.dumps(formulas,indent=2)+"\n")
    examples = score.head(3).copy()
    extra = [name for name in SETS["combined"] if name not in examples]
    examples = examples.merge(test[["date","symbol"]+extra],on=["date","symbol"],validate="one_to_one")
    examples.to_csv(args.output/"first-three-examples.csv",index=False)
    families = list(plan["models"])
    groups = plan["feature_sets"]
    values = np.array([[compared.loc[f"{family}__{group}","sharpe"] for group in groups] for family in families])
    fig,axes = plt.subplots(1,2,figsize=(12,5),layout="constrained")
    image = axes[0].imshow(values,cmap="RdBu",vmin=-2.5,vmax=2.5,aspect="auto")
    axes[0].set_xticks(range(3),["Gap only","Context only","Combined"])
    axes[0].set_yticks(range(4),["Ridge","Elastic Net","Random Forest","Hist. Boost"])
    axes[0].set_title("Exploratory 2023–2024 net Sharpe")
    for i in range(4):
        for j in range(3):
            axes[0].text(j,i,f"{values[i,j]:.2f}",ha="center",va="center",color="white" if abs(values[i,j])>1.3 else "black")
    fig.colorbar(image,ax=axes[0],shrink=0.7)
    names = ["gap_raw","gap_volume"]+[f"{family}__combined" for family in families]+["hist_boost__context"]
    labels = ["Raw gap","Volume-weighted gap","Ridge / combined","Elastic Net / combined",
              "Random Forest / combined","Hist. Boost / combined","Hist. Boost / context *"]
    y = np.arange(len(names))
    axes[1].scatter(training.loc[names,"sharpe"],y,label="Training OOF 2021–2022",marker="o",s=40)
    axes[1].scatter(compared.loc[names,"sharpe"],y,label="Reused validation 2023–2024",marker="x",s=50)
    axes[1].axvline(0,color="gray",linewidth=0.8)
    axes[1].set_yticks(y,labels)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Net Sharpe (5 bps assumed round-trip cost)")
    axes[1].set_title("* Selected using training OOF only")
    fig.legend(*axes[1].get_legend_handles_labels(),loc="outside lower center",ncol=2,fontsize=9)
    fig.suptitle("Round 2: 12 ML candidates + 2 baselines | 2025 not evaluated",fontsize=12)
    fig.savefig(args.output/"method-comparison.png",dpi=170)
    fig.savefig(args.output/"method-comparison.pdf",metadata={"CreationDate":None,"ModDate":None})
    plt.close(fig)
    evidence = {"status":"post-hoc descriptive explanation; no tuning or qualification",
                "round":2,"holdout_opened":False,
                "input_summary_sha256":hashlib.sha256((args.results/"summary.json").read_bytes()).hexdigest(),
                "analysis_code_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "artifacts_sha256":{file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(args.output.iterdir())}}
    (args.output/"analysis.json").write_text(json.dumps(evidence,indent=2)+"\n")
    print(pd.DataFrame(controls).to_string(index=False))


if __name__=="__main__":
    main()
