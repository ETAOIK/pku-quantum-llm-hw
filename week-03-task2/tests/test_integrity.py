"""Financial research integrity checks against generated artifacts."""
import json
import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build_features import ROOT, HORIZONS, seconds, hash_file
from research import fee, nonoverlap


class IntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=pd.read_parquet(ROOT/"cache/features.parquet")
        cls.audit=json.loads((ROOT/"results/data_audit.json").read_text())

    def test_hhmmss_milliseconds(self):
        np.testing.assert_allclose(seconds([93000580,113000000,145659999]),[34200.580,41400,53819.999])

    def test_original_sources_unchanged(self):
        for f in self.audit["files"].values():
            self.assertEqual(hash_file(Path(f["path"])),f["sha256"])

    def test_reconciliation_and_identifiers(self):
        self.assertTrue(self.audit["symbol_sets_equal"])
        self.assertEqual(self.audit["auction_volume_reconciliation_max_abs"],0)
        self.assertEqual(self.audit["after_volume_reconciliation_max_abs"],0)
        self.assertLessEqual(self.audit["auction_amount_reconciliation_max_abs_fen"],50)
        self.assertEqual(self.audit["combined_channel_seq_duplicates"],0)
        self.assertEqual(self.audit["unmatched_cancellation_messages"],0)
        self.assertEqual(self.audit["negative_cancel_lifetimes"],0)

    def test_quote_features_available_before_decision(self):
        g=self.p[self.p.mid.notna()]
        self.assertTrue((g.available<=g.t).all())
        self.assertTrue((g.quote_age>=1).all())
        self.assertTrue((g.quote_age<=8).all())

    def test_labels_do_not_cross_sessions_or_split_boundaries(self):
        end=self.p.split.map({"train":41400,"validation":50400,"test":53820}).fillna(0)
        session_end=self.p.session.map({0:41400,1:53820})
        for h in HORIZONS:
            good=self.p[f"y_{h}"].notna()
            self.assertTrue((self.p.loc[good,"t"]+5+h<end[good]).all())
            self.assertTrue((self.p.loc[good,"t"]+5+h<session_end[good]).all())

    def test_entry_quote_is_delayed_and_label_is_reproducible(self):
        for _,g in self.p.groupby(["Symbol","session"]):
            np.testing.assert_allclose(g.entry_mid,g.mid.shift(-1),equal_nan=True)
            for h in HORIZONS:
                valid=g[f"y_{h}"].notna()
                expected=(g.mid.shift(-(h//5+1))/g.mid.shift(-1)-1)*10000
                np.testing.assert_allclose(g.loc[valid,f"y_{h}"],expected[valid])

    def test_transaction_fees_and_minimum(self):
        self.assertAlmostEqual(fee(10000,"buy"),5.1)
        self.assertAlmostEqual(fee(10000,"sell"),10.1)
        self.assertAlmostEqual(fee(100000,"sell"),61)

    def test_nonoverlap_uses_exit_after_entry_delay(self):
        g=pd.DataFrame({"Symbol":[1]*5,"t":[0,60,65,125,130]})
        self.assertEqual(nonoverlap(g,60).t.tolist(),[0,65,130])

    def test_inventory_budget_and_completion(self):
        e=pd.read_csv(ROOT/"results/inventory_episodes.csv")
        self.assertFalse(e.duplicated(["candidate","split","policy","Symbol"]).any())
        self.assertTrue((e.shares==1000).all())
        self.assertTrue((e.sellable_after==0).all())
        self.assertTrue((e.buy_t>e.sell_t).all())
        completed=e[e.completed]
        self.assertTrue((completed.new_shares_after==1000).all())
        np.testing.assert_allclose(completed.net_cny,completed.gross_cny-completed.fees_cny)
        self.assertTrue(e.loc[~e.completed,"net_cny"].isna().all())
        cash=pd.read_csv(ROOT/"results/inventory_cash_ledger.csv")
        self.assertTrue((cash.cash_after>=0).all())
        for key,scenario in cash.groupby(["candidate","split","policy"]):
            np.testing.assert_allclose(scenario.cash_after,100000+scenario.cash_delta.cumsum())
            cycles=e.set_index(["candidate","split","policy"]).sort_index().loc[key]
            self.assertAlmostEqual(scenario.cash_delta.sum(),cycles.net_cny.sum())

    def test_selection_uses_validation_only(self):
        m=pd.read_csv(ROOT/"results/candidate_metrics.csv")
        s=json.loads((ROOT/"results/selection.json").read_text())
        best=m[m.split=="validation"].sort_values("net_edge_bps",ascending=False).iloc[0]
        self.assertEqual(s["selected"],best.candidate)
        self.assertEqual(len(m[m.split=="validation"]),103)
        self.assertFalse(m.duplicated(["candidate","split"]).any())
        events=pd.read_csv(ROOT/"results/selected_test_events.csv")
        self.assertAlmostEqual(events.net_edge_bps.mean(),s["test"]["net_edge_bps"])
        latency=pd.read_csv(ROOT/"results/latency_sensitivity.csv")
        self.assertAlmostEqual(latency.iloc[0].net_edge_bps,s["test"]["net_edge_bps"])


if __name__=="__main__":unittest.main()
