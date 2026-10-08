"""用假原生 API 检查异步流程；不加载 SDK、不连接服务器。"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch


path = Path(__file__).resolve().parents[1] / "demo.py"
spec = importlib.util.spec_from_file_location("ctp_minimal_demo", path)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)

SETTINGS = {"userid": "test-user", "password": "test-secret", "brokerid": "test-broker",
            "td_address": "tcp://td.test:1", "md_address": "tcp://md.test:2",
            "appid": "test-app", "auth_code": "test-auth"}


class FakeApi:
    instances = []
    auth_error = 0
    login_error = 0
    subscribe_error = 0
    send_result = 0
    settlement_error = 0
    order_result = 0
    order_error = 0

    def __init__(self):
        self.calls = []
        self.closed = False
        self.instances.append(self)

    def createFtdcTraderApi(self, *args):
        self.calls.append(("create_td", args))

    def createFtdcMdApi(self, *args):
        self.calls.append(("create_md", args))

    def subscribePrivateTopic(self, mode):
        self.calls.append(("private", mode))

    def subscribePublicTopic(self, mode):
        self.calls.append(("public", mode))

    def registerFront(self, address):
        self.calls.append(("front", address))

    def init(self):
        self.calls.append(("init",))
        self.onFrontConnected()

    def reqAuthenticate(self, request, reqid):
        self.calls.append(("authenticate", request.copy(), reqid))
        if not self.send_result:
            self.onRspAuthenticate({}, {"ErrorID": self.auth_error}, reqid, True)
        return self.send_result

    def reqUserLogin(self, request, reqid):
        self.calls.append(("login", request.copy(), reqid))
        if not self.send_result:
            self.onRspUserLogin({"MaxOrderRef": " 10", "FrontID": 1, "SessionID": 2,
                                 "TradingDay": "20261008"}, {"ErrorID": self.login_error}, reqid, True)
        return self.send_result

    def reqSettlementInfoConfirm(self, request, reqid):
        self.calls.append(("settlement", request.copy()))
        self.onRspSettlementInfoConfirm({}, {"ErrorID": self.settlement_error}, reqid, True)
        return 0

    def reqQryInstrument(self, request, reqid):
        self.calls.append(("query_contract", request.copy()))
        self.onRspQryInstrument({"InstrumentID": "rb2701", "ExchangeID": "SHFE",
                                 "PriceTick": 1, "IsTrading": True,
                                 "MinLimitOrderVolume": 1, "MaxLimitOrderVolume": 100},
                                {"ErrorID": 0}, reqid, True)
        return 0

    def reqOrderInsert(self, request, reqid):
        self.calls.append(("order", request.copy()))
        if self.order_error:
            self.onRspOrderInsert(request, {"ErrorID": self.order_error}, reqid, True)
        return self.order_result

    def reqOrderAction(self, request, reqid):
        self.calls.append(("cancel", request.copy()))
        self.onRtnOrder({**request, "OrderStatus": "5", "VolumeTraded": 0, "StatusMsg": "已撤单"})
        return 0

    def subscribeMarketData(self, symbol):
        self.calls.append(("subscribe", symbol))
        if self.send_result:
            return self.send_result
        self.onRspSubMarketData({"InstrumentID": symbol}, {"ErrorID": self.subscribe_error}, 1, True)
        if not self.subscribe_error:
            self.onRtnDepthMarketData({"InstrumentID": symbol, "LastPrice": 100,
                                      "BidPrice1": 99, "AskPrice1": 101, "Volume": 1})
        return 0

    def exit(self):
        self.closed = True


class DemoTests(unittest.TestCase):
    def setUp(self):
        FakeApi.instances = []
        FakeApi.auth_error = FakeApi.login_error = FakeApi.subscribe_error = FakeApi.send_result = 0
        FakeApi.settlement_error = FakeApi.order_result = FakeApi.order_error = 0
        package = types.ModuleType("vnpy_ctp")
        api = types.ModuleType("vnpy_ctp.api")
        api.MdApi = api.TdApi = FakeApi
        self.modules = patch.dict(sys.modules, {"vnpy_ctp": package, "vnpy_ctp.api": api})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.output = io.StringIO()
        self.stdout = contextlib.redirect_stdout(self.output)
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def run_demo(self, package_version="6.7.11.4"):
        with tempfile.TemporaryDirectory() as tmp, patch.object(demo, "HERE", Path(tmp)), \
                patch.object(demo, "version", return_value=package_version):
            return demo.run(SETTINGS, ["rb2701"], 0.1, 0.001)

    def test_auth_login_subscribe_print_and_cleanup(self):
        previous_cwd = Path.cwd()
        self.assertEqual(self.run_demo(), 0)
        td, md = FakeApi.instances
        self.assertEqual([c[0] for c in td.calls],
                         ["create_td", "private", "public", "front", "init", "authenticate", "login"])
        self.assertEqual(td.calls[-2][1]["AppID"], "test-app")
        self.assertEqual(td.calls[-1][1]["Password"], "test-secret")
        self.assertEqual(td.calls[0][1][1], False)
        self.assertEqual([c[0] for c in md.calls], ["create_md", "front", "init", "login", "subscribe"])
        self.assertIn('"InstrumentID": "rb2701"', self.output.getvalue())
        self.assertIn('"LastPrice": 100', self.output.getvalue())
        self.assertNotIn("test-secret", self.output.getvalue())
        self.assertTrue(td.closed and md.closed)
        self.assertEqual(Path.cwd(), previous_cwd)

    def test_mac_legacy_api_uses_one_creation_argument(self):
        self.run_demo("6.7.7.2")
        td, md = FakeApi.instances
        self.assertEqual(len(td.calls[0][1]), 1)
        self.assertEqual(len(md.calls[0][1]), 1)

    def test_auth_rejected_does_not_login_or_subscribe(self):
        FakeApi.auth_error = 63
        with self.assertRaisesRegex(RuntimeError, "交易认证失败"):
            self.run_demo()
        td, md = FakeApi.instances
        self.assertNotIn("login", [c[0] for c in td.calls])
        self.assertEqual(md.calls, [])
        self.assertTrue(td.closed)

    def test_login_rejected_does_not_subscribe(self):
        FakeApi.login_error = 3
        with self.assertRaisesRegex(RuntimeError, "交易登录失败"):
            self.run_demo()
        self.assertEqual(FakeApi.instances[1].calls, [])
        self.assertTrue(FakeApi.instances[0].closed)

    def test_md_login_failure_cannot_subscribe(self):
        td, md = demo.create_clients(SETTINGS)
        md.onRspUserLogin({}, {"ErrorID": 3, "ErrorMsg": "denied"}, 1, True)
        self.assertTrue(md.ready.is_set())
        self.assertFalse(md.first_tick.is_set())
        self.assertIn("行情登录失败", md.error)
        self.assertEqual(md.calls, [])

    def test_subscription_rejected_fails_and_closes_both_apis(self):
        FakeApi.subscribe_error = 31
        with self.assertRaisesRegex(RuntimeError, "行情订阅失败"):
            self.run_demo()
        self.assertTrue(all(api.closed for api in FakeApi.instances))
        self.assertNotIn("行情 {", self.output.getvalue())

    def test_local_request_failure_stops_startup(self):
        FakeApi.send_result = -1
        with self.assertRaisesRegex(RuntimeError, "请求发送失败"):
            self.run_demo()
        self.assertTrue(FakeApi.instances[0].closed)

    def test_timeout_and_disconnect_are_reported(self):
        td, md = demo.create_clients(SETTINGS)
        with self.assertRaises(TimeoutError):
            demo.wait_for(Event(), [td], "测试连接", 0.001)
        md.onFrontDisconnected(4097)
        self.assertFalse(md.ready.is_set())
        self.assertFalse(md.first_tick.is_set())
        self.assertEqual(md.error, "")
        self.assertIn("等待 SDK 自动重连", self.output.getvalue())

    def test_default_wait_does_not_exit_after_thirty_seconds(self):
        td, md = demo.create_clients(SETTINGS)
        event = Event()
        waits = []

        def wait(seconds):
            waits.append(seconds)
            if len(waits) == 2:
                event.set()

        with patch.object(event, "wait", side_effect=wait), \
                patch.object(demo, "monotonic", side_effect=range(0, 2000, 100)):
            demo.wait_for(event, [td], "首条行情", 0)
        self.assertEqual(len(waits), 2)
        self.assertIn("仍在等待首条行情", self.output.getvalue())

    def test_md_reconnect_logs_in_and_resubscribes_all_symbols(self):
        td, md = demo.create_clients(SETTINGS)
        md.symbols = demo.DEFAULT_SYMBOLS
        md.onFrontConnected()
        md.onFrontDisconnected(4097)
        self.assertFalse(md.ready.is_set())
        self.assertFalse(md.first_tick.is_set())
        md.onFrontConnected()
        self.assertEqual([c[1] for c in md.calls if c[0] == "subscribe"],
                         demo.DEFAULT_SYMBOLS * 2)
        self.assertEqual(len([c for c in md.calls if c[0] == "login"]), 2)
        self.assertTrue(md.ready.is_set() and md.first_tick.is_set())
        for symbol in demo.DEFAULT_SYMBOLS:
            self.assertEqual(self.output.getvalue().count(f'"InstrumentID": "{symbol}"'), 2)

    def test_continuous_run_exits_only_on_interrupt_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(demo, "HERE", Path(tmp)), \
                patch.object(demo, "version", return_value="6.7.7.2"), \
                patch.object(demo, "sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                demo.run(SETTINGS, demo.DEFAULT_SYMBOLS, 0, 0)
        self.assertTrue(all(api.closed for api in FakeApi.instances))

    def test_cli_defaults_to_three_symbols_and_continuous_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps(SETTINGS))
            with patch.object(demo, "run", return_value=0) as run:
                self.assertEqual(demo.main(["--config", str(config)]), 0)
                run.assert_called_once_with(SETTINGS, ["rb2701", "ag2612", "au2612"], 0, 0)

    def test_empty_config_rejected_before_loading_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps({**SETTINGS, "password": ""}))
            with patch.object(demo, "run") as run, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(demo.main(["--config", str(config)]), 1)
                run.assert_not_called()

    def trading_client(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.object(demo, "HERE", Path(temp.name)):
            td, md = demo.create_clients(SETTINGS, "rb2701")
        td.journal.parent.mkdir()
        td.onFrontConnected()
        return td

    def tick(self, **changes):
        return {"InstrumentID": "rb2701", "TradingDay": "20261008", "LastPrice": 101,
                "BidPrice1": 100, "AskPrice1": 102, "BidVolume1": 1, "AskVolume1": 1,
                "LowerLimitPrice": 90, "UpperLimitPrice": 110, **changes}

    def test_settlement_and_contract_must_be_ready_before_trading(self):
        FakeApi.settlement_error = 42
        td = self.trading_client()
        td.try_buy(self.tick(), 100)
        self.assertIn("结算确认失败", td.error)
        self.assertNotIn("query_contract", [c[0] for c in td.calls])
        self.assertFalse(td.attempted)

    def test_strict_threshold_and_invalid_quotes_do_not_trigger(self):
        td = self.trading_client()
        for change in ({"LastPrice": 99}, {"LastPrice": 100}, {"AskPrice1": 1.7976931348623157e308},
                       {"BidPrice1": float("nan")}, {"AskVolume1": 0}, {"BidPrice1": 103},
                       {"TradingDay": "20261007"}, {"AskPrice1": 102.5}, {"UpperLimitPrice": 101}):
            with self.subTest(change=change):
                td.try_buy(self.tick(**change), 100)
        self.assertFalse(td.attempted)
        self.assertFalse(td.journal.exists())

    def test_trigger_sends_one_buy_open_at_ask_and_locks_restart(self):
        td = self.trading_client()
        for _ in range(3):
            td.try_buy(self.tick(), 100)
        orders = [c[1] for c in td.calls if c[0] == "order"]
        self.assertEqual(len(orders), 1)
        request = orders[0]
        self.assertEqual((request["Direction"], request["CombOffsetFlag"], request["VolumeTotalOriginal"]),
                         ("0", "0", 1))
        self.assertEqual(request["LimitPrice"], 102)
        self.assertEqual(request["OrderRef"], "11")
        self.assertNotIn("Password", request)
        self.assertNotIn("test-secret", td.journal.read_text())
        with patch.object(demo, "HERE", td.journal.parents[1]):
            with self.assertRaisesRegex(RuntimeError, "已有单次交易记录"):
                demo.run(SETTINGS, ["rb2701"], 0, 0, "rb2701", 100)

    def test_order_ack_alone_is_not_a_completed_trade_and_fills_are_deduplicated(self):
        td = self.trading_client()
        td.try_buy(self.tick(), 100)
        order = {"InstrumentID": "rb2701", "OrderRef": "11", "FrontID": 1,
                 "SessionID": 2, "OrderStatus": "0", "VolumeTraded": 1}
        td.onRtnOrder({**order, "SessionID": 99})
        self.assertFalse(td.all_traded)
        td.onRtnOrder(order)
        self.assertFalse(td.completed.is_set())
        trade = {"InstrumentID": "rb2701", "OrderRef": "11", "ExchangeID": "SHFE",
                 "TradeID": "trade-1", "TradeDate": "20261008", "TradeTime": "09:05:00",
                 "Price": 102, "Volume": 1}
        td.onRtnTrade({**trade, "OrderRef": "9"})
        self.assertEqual(td.filled, 0)
        td.onRtnTrade(trade)
        td.onRtnTrade(trade)
        self.assertEqual(td.filled, 1)
        self.assertTrue(td.completed.is_set())
        self.assertEqual(json.loads(td.journal.read_text())["state"], "completed")

    def test_rejection_and_send_failure_are_not_retried(self):
        for attribute, value in (("order_error", 31), ("order_result", -2)):
            with self.subTest(attribute=attribute):
                setattr(FakeApi, attribute, value)
                td = self.trading_client()
                td.try_buy(self.tick(), 100)
                td.try_buy(self.tick(), 100)
                self.assertEqual(len([c for c in td.calls if c[0] == "order"]), 1)
                self.assertFalse(td.completed.is_set())
                self.assertTrue(td.error)
                setattr(FakeApi, attribute, 0)

    def test_disconnect_requires_new_trading_readiness(self):
        td = self.trading_client()
        td.onFrontDisconnected(4097)
        td.try_buy(self.tick(), 100)
        self.assertFalse(td.attempted)

    def test_invalid_sdk_prices_print_as_null(self):
        td, md = demo.create_clients(SETTINGS)
        md.onRtnDepthMarketData(self.tick(AskPrice1=1.7976931348623157e308))
        self.assertIn('"AskPrice1": null', self.output.getvalue())

    def test_pending_order_is_cancelled_on_exit(self):
        td = self.trading_client()
        td.try_buy(self.tick(), 100)
        td.cancel_pending()
        self.assertTrue(td.order_done)
        self.assertFalse(td.completed.is_set())
        cancel = [c[1] for c in td.calls if c[0] == "cancel"]
        self.assertEqual(len(cancel), 1)
        self.assertEqual((cancel[0]["FrontID"], cancel[0]["SessionID"], cancel[0]["OrderRef"]),
                         (1, 2, "11"))

    def test_cli_rejects_other_fronts_before_running_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps(SETTINGS))
            with patch.object(demo, "run") as run, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(demo.main(["--config", str(config), "--trade", "--threshold", "100"]), 1)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
