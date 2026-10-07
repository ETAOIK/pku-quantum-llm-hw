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
            self.onRspUserLogin({}, {"ErrorID": self.login_error}, reqid, True)
        return self.send_result

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
        self.assertEqual(td.calls[0][1][1], True)
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
        with self.assertRaisesRegex(RuntimeError, "行情连接断开"):
            demo.wait_for(md.first_tick, [md], "首条行情", 0.1)

    def test_empty_config_rejected_before_loading_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps({**SETTINGS, "password": ""}))
            with patch.object(demo, "run") as run, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(demo.main(["--config", str(config)]), 1)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
