import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factors
import run


def bars(size=70):
    i = np.arange(size)
    close = 100+0.2*i+np.sin(i)
    opening = close+0.2*np.cos(i)
    return pd.DataFrame({"date":pd.bdate_range("2020-01-01",periods=size),
                         "open":opening,"high":np.maximum(opening,close)+1,
                         "low":np.minimum(opening,close)-1,"close":close,
                         "volume":30000+i*20,"hold":20000+i*5,"settle":close})


def write_fixture(root, frames):
    (root/"data").mkdir(exist_ok=True)
    entries = []
    for symbol, frame in frames.items():
        data = frame.rename(columns={"date":"d","open":"o","high":"h","low":"l","close":"c",
                                     "volume":"v","hold":"p","settle":"s"}).copy()
        data.d = data.d.dt.strftime("%Y-%m-%d")
        path = root/"data"/f"{symbol}.json"
        path.write_text(data.to_json(orient="records"))
        entries.append({"symbol":symbol,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    (root/"data-lock.json").write_text(json.dumps({"contracts":entries}))


class MiningTests(unittest.TestCase):
    def test_future_edits_do_not_change_past_factors(self):
        original = bars()
        changed = original.copy()
        changed.loc[45:, ["open","high","low","close","volume","hold"]] *= 7
        pd.testing.assert_frame_equal(factors.compute(original).iloc[:45], factors.compute(changed).iloc[:45])

    def test_gap_uses_same_contract_close_not_settlement(self):
        frame = bars()
        frame.loc[35,"open"] = frame.loc[34,"close"]*1.02
        frame.loc[34,"settle"] *= 10
        self.assertAlmostEqual(factors.compute(frame).loc[35,"gap_raw"],np.log(1.02))
        scaled = frame.copy()
        scaled[["open","high","low","close"]] *= 10
        np.testing.assert_allclose(factors.compute(frame).gap_raw, factors.compute(scaled).gap_raw, equal_nan=True)

    def test_missing_bar_is_not_skipped_in_gap(self):
        frame = bars()
        frame.loc[34,["open","high","low","close"]] = np.nan
        self.assertTrue(np.isnan(factors.compute(frame).loc[35,"gap_raw"]))

    def test_contract_selection_and_target_timing(self):
        a, b = bars(), bars()
        b.volume = 20000
        plan = {"holdout":["2025-01-01","2025-12-31"],"train":["2020-01-01","2022-12-31"],
                "min_signal_volume":10000,"min_signal_hold":10000}
        with tempfile.TemporaryDirectory() as tmp, patch.object(run,"HERE",Path(tmp)):
            root = Path(tmp)
            write_fixture(root,{"RB2105":a,"RB2110":b})
            first, _, _ = run.load_panel(plan)
            row = first[first.date == a.loc[35,"date"]].iloc[0]
            self.assertEqual(row.symbol,"RB2105")
            self.assertEqual(row.entry_date,a.loc[36,"date"])
            self.assertAlmostEqual(row.target,a.loc[36,"close"]/a.loc[36,"open"]-1)
            b.loc[36,"volume"] = 999999
            write_fixture(root,{"RB2105":a,"RB2110":b})
            second, _, _ = run.load_panel(plan)
            pd.testing.assert_series_equal(row,second[second.date==row.date].iloc[0])

    def test_missing_target_never_causes_future_contract_fallback(self):
        a, b = bars(), bars()
        b.volume = 20000
        a.loc[36,["open","high","low","close"]] = 0
        plan = {"holdout":["2025-01-01","2025-12-31"],"train":["2020-01-01","2022-12-31"],
                "min_signal_volume":10000,"min_signal_hold":10000}
        with tempfile.TemporaryDirectory() as tmp, patch.object(run,"HERE",Path(tmp)):
            write_fixture(Path(tmp),{"RB2105":a,"RB2110":b})
            panel,_,audit = run.load_panel(plan)
            row = panel[panel.date==a.loc[35,"date"]].iloc[0]
            self.assertEqual(row.symbol,"RB2105")
            self.assertTrue(np.isnan(row.target))
            self.assertEqual(audit["invalid_rows"],1)

    def test_costs_cash_and_short_direction(self):
        calendar = pd.date_range("2020-01-01",periods=2)
        frame = pd.DataFrame({"date":calendar-pd.Timedelta(days=1),"entry_date":calendar,
                              "product":["RB","RB"],"symbol":["RB2105","RB2105"],
                              "target":[-0.01,0.03],"gap_raw":[-0.02,0.0]})
        metrics,daily,obs = run.evaluate(frame,calendar,"gap_raw",{"RB":0,"AG":0,"AU":0},5)
        self.assertEqual(obs.position.tolist(),[-1,0])
        self.assertEqual(metrics["trades"],1)
        self.assertAlmostEqual(daily.net.iloc[0],(0.01-0.0005)/3)
        self.assertEqual(daily.net.iloc[1],0)

    def test_thresholds_are_training_only(self):
        frame = pd.DataFrame({"product":list(run.PRODUCTS)*10,"gap_raw":np.arange(30)/1000})
        expected = run.thresholds(frame,"gap_raw")
        future = pd.DataFrame({"product":list(run.PRODUCTS),"gap_raw":[1000]*3})
        self.assertNotEqual(expected,run.thresholds(pd.concat([frame,future]),"gap_raw"))
        self.assertEqual(expected,run.thresholds(frame,"gap_raw"))

    def test_validation_requires_all_three_conditions(self):
        good = {"trades":50,"rank_ic":0.03,"mean_net_bps":0.1}
        self.assertTrue(run.passes(good,50))
        for key,value in (("trades",49),("rank_ic",0),("mean_net_bps",0)):
            self.assertFalse(run.passes({**good,key:value},50))


if __name__ == "__main__":
    unittest.main()
