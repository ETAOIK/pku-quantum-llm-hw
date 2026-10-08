import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ml
from test_mining import bars


def synthetic_panel():
    dates = pd.date_range("2020-01-03","2025-12-31",freq="W-FRI")
    frame = pd.DataFrame([(date,product) for date in dates for product in ml.PRODUCTS],columns=["entry_date","product"])
    frame["date"] = frame.entry_date-pd.Timedelta(days=1)
    frame["symbol"] = frame["product"]+"2612"
    rng = np.random.default_rng(5)
    for col in ml.FACTORS+ml.CONTEXT:
        frame[col] = rng.normal(size=len(frame))
    for product in ml.PRODUCTS:
        frame[f"product_{product}"] = (frame["product"]==product).astype(float)
    frame["target"] = frame.gap_raw*0.01+rng.normal(0,0.02,size=len(frame))
    return frame


class MLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((ml.HERE/"plan-ml.json").read_text())

    def test_context_is_causal(self):
        a,b = bars(),bars()
        b.loc[45:,["open","high","low","close","volume","hold"]] *= 8
        pd.testing.assert_frame_equal(ml.context_features(a).iloc[:45],ml.context_features(b).iloc[:45])

    def test_flat_bar_has_neutral_close_location(self):
        frame = bars()
        frame.loc[40,["open","high","low","close"]] = 100
        self.assertEqual(ml.context_features(frame).loc[40,"close_location"],0)

    def test_date_groups_and_label_embargo(self):
        panel = synthetic_panel()
        fit,score = ml.time_fold(panel,"2021-01-01","2021-06-30")
        self.assertLess(fit.entry_date.max(),score.date.min())
        self.assertTrue(score.groupby("entry_date").size().eq(3).all())
        self.assertFalse(set(fit.entry_date)&set(score.entry_date))

    def test_future_labels_cannot_change_earlier_oof_or_comparison(self):
        a,b = synthetic_panel(),synthetic_panel()
        b.loc[b.entry_date>="2023-01-01","target"] = 1000000
        x,comp,_,_,_ = ml.fit_predict(a,"ridge","gap",self.plan)
        y,comp_changed,_,_,_ = ml.fit_predict(b,"ridge","gap",self.plan)
        pd.testing.assert_series_equal(x,y)
        pd.testing.assert_series_equal(comp,comp_changed)
        self.assertLess(comp.index.max(),b[b.entry_date>="2025-01-01"].index.min())

    def test_future_training_edits_do_not_rewrite_first_oof_fold(self):
        a,b = synthetic_panel(),synthetic_panel()
        b.loc[b.entry_date>="2021-07-01","target"] *= -500
        x,_,_,_,_ = ml.fit_predict(a,"ridge","gap",self.plan)
        y,_,_,_,_ = ml.fit_predict(b,"ridge","gap",self.plan)
        first = (a.entry_date>="2021-01-01")&(a.entry_date<="2021-06-30")
        pd.testing.assert_series_equal(x[first],y[first])

    def test_scaler_does_not_fit_on_prediction_rows(self):
        panel = synthetic_panel()
        fit,score = ml.time_fold(panel,"2021-01-01","2021-06-30")
        cols = ml.SETS["gap"]+ml.PRODUCT_COLUMNS
        model = ml.estimator("ridge",self.plan).fit(fit[cols],fit.target*10000)
        mean = model[0].mean_.copy()
        model.predict(score[cols]*10000)
        np.testing.assert_allclose(model[0].mean_,fit[cols].mean().to_numpy())
        np.testing.assert_array_equal(mean,model[0].mean_)

    def test_inputs_exclude_targets_and_timestamps(self):
        for columns in ml.SETS.values():
            self.assertFalse(set(columns)&{"target","date","entry_date","symbol"})
        self.assertEqual(len(self.plan["models"])*len(self.plan["feature_sets"]),12)
        self.assertFalse(ml.estimator("hist_boost",self.plan).early_stopping)


if __name__=="__main__":
    unittest.main()
