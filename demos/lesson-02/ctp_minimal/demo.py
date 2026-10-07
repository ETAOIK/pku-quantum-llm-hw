"""底层 CTP API：交易认证登录、行情登录订阅、打印行情。"""

import argparse
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path
from threading import Event
from time import monotonic, sleep


HERE = Path(__file__).resolve().parent
DEFAULT_SYMBOLS = ["rb2701", "ag2612", "au2612"]


def fail(api, message):
    api.error = message
    api.ready.set()
    print(message, flush=True)


def check_response(api, label, error):
    if error.get("ErrorID", 0):
        fail(api, f"{label}失败：{error['ErrorID']} {error.get('ErrorMsg', '')}")
        return False
    return True


def send_request(api, method, request, label):
    api.reqid += 1
    result = method(request, api.reqid)
    if result:
        fail(api, f"{label}请求发送失败：返回码 {result}")


def create_clients(settings):
    # 延迟导入：--help、配置检查和离线测试不要求加载原生 SDK。
    from vnpy_ctp.api import MdApi, TdApi

    login = {"UserID": settings["userid"], "Password": settings["password"],
             "BrokerID": settings["brokerid"]}

    class DemoTdApi(TdApi):
        def __init__(self):
            super().__init__()
            self.reqid, self.error, self.ready = 0, "", Event()

        def onFrontConnected(self):
            print("交易前置已连接，发起认证", flush=True)
            request = {"UserID": settings["userid"], "BrokerID": settings["brokerid"],
                       "AppID": settings["appid"], "AuthCode": settings["auth_code"]}
            send_request(self, self.reqAuthenticate, request, "交易认证")

        def onRspAuthenticate(self, data, error, reqid, last):
            if check_response(self, "交易认证", error):
                print("交易认证成功，发起登录", flush=True)
                send_request(self, self.reqUserLogin, login, "交易登录")

        def onRspUserLogin(self, data, error, reqid, last):
            if check_response(self, "交易登录", error):
                print("交易登录成功", flush=True)
                self.ready.set()

        def onFrontDisconnected(self, reason):
            self.ready.clear()
            print(f"交易连接断开：{reason}；等待 SDK 自动重连", flush=True)

        def onRspError(self, error, reqid, last):
            check_response(self, "交易接口", error)

    class DemoMdApi(MdApi):
        def __init__(self):
            super().__init__()
            self.reqid, self.error, self.ready = 0, "", Event()
            self.first_tick = Event()
            self.symbols = []

        def onFrontConnected(self):
            print("行情前置已连接，发起登录", flush=True)
            send_request(self, self.reqUserLogin, login, "行情登录")

        def onRspUserLogin(self, data, error, reqid, last):
            if check_response(self, "行情登录", error):
                print("行情登录成功", flush=True)
                for symbol in self.symbols:
                    result = self.subscribeMarketData(symbol)
                    if result:
                        fail(self, f"订阅 {symbol} 请求发送失败：返回码 {result}")
                self.ready.set()

        def onRspSubMarketData(self, data, error, reqid, last):
            if check_response(self, "行情订阅", error):
                print(f"订阅确认：{data.get('InstrumentID', '')}", flush=True)

        def onRtnDepthMarketData(self, data):
            fields = ("InstrumentID", "TradingDay", "ActionDay", "UpdateTime",
                      "UpdateMillisec", "LastPrice", "BidPrice1", "AskPrice1", "Volume")
            print("行情 " + json.dumps({k: data.get(k) for k in fields},
                                      ensure_ascii=False), flush=True)
            self.first_tick.set()

        def onFrontDisconnected(self, reason):
            self.ready.clear()
            self.first_tick.clear()
            print(f"行情连接断开：{reason}；等待 SDK 自动重连并恢复订阅", flush=True)

        def onRspError(self, error, reqid, last):
            check_response(self, "行情接口", error)

    return DemoTdApi(), DemoMdApi()


def wait_for(event, clients, label, timeout):
    deadline = monotonic() + timeout if timeout else None
    next_notice = monotonic() + 30
    while True:
        for api in clients:
            if api.error:
                raise RuntimeError(api.error)
        if event.is_set():
            return
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError(f"{label}超时（{timeout:g} 秒）；请检查前置、服务时段或合约")
        if monotonic() >= next_notice:
            print(f"仍在等待{label}，按 Ctrl+C 退出", flush=True)
            next_notice = monotonic() + 30
        event.wait(0.1)


def run(settings, symbols, timeout, duration):
    # 包入口间接导入 vnpy；隔离其 .vntrader 文件，避免读取用户其他交易配置。
    runtime = HERE / "runtime"
    (runtime / ".vntrader").mkdir(parents=True, exist_ok=True)
    previous_cwd = Path.cwd()
    started = []
    try:
        os.chdir(runtime)
        td, md = create_clients(settings)
        md.symbols = symbols
        package_version = version("vnpy_ctp")
        print(f"vnpy_ctp {package_version}；订阅 {', '.join(symbols)}", flush=True)
        print("持续等待连接和行情，按 Ctrl+C 退出", flush=True)
        new_api = tuple(map(int, package_version.split(".")[:3])) >= (6, 7, 11)
        for api, name, address in ((td, "td", settings["td_address"]),
                                   (md, "md", settings["md_address"])):
            folder = runtime / name
            folder.mkdir(exist_ok=True)
            create = td.createFtdcTraderApi if api is td else md.createFtdcMdApi
            args = (str(folder) + os.sep, True) if new_api else (str(folder) + os.sep,)
            create(*args)
            if api is td:
                td.subscribePrivateTopic(2)
                td.subscribePublicTopic(2)
            api.registerFront(address)
            api.init()
            started.append(api)
            wait_for(api.ready, started, f"{name} 连接/登录", timeout)

        wait_for(md.first_tick, started, "首条行情", timeout)
        print("已收到行情，按 Ctrl+C 退出", flush=True)
        deadline = monotonic() + duration if duration else None
        while deadline is None or monotonic() < deadline:
            for api in started:
                if api.error:
                    raise RuntimeError(api.error)
            sleep(0.1)
        return 0
    finally:
        # 必须在主线程关闭；原生 exit 会等待回调线程结束。
        for api in reversed(started):
            api.exit()
        os.chdir(previous_cwd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "config.local.json")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="CTP 合约代码，无交易所后缀")
    parser.add_argument("--timeout", type=float, default=0, help="每个启动阶段的超时秒数；0 表示持续等待")
    parser.add_argument("--duration", type=float, default=0, help="首条行情后运行秒数；0 表示持续运行")
    args = parser.parse_args(argv)
    if args.timeout < 0 or args.duration < 0:
        parser.error("timeout 和 duration 不能小于 0")
    try:
        settings = json.loads(args.config.read_text())
        required = ("userid", "password", "brokerid", "td_address", "md_address", "appid", "auth_code")
        if not isinstance(settings, dict):
            raise ValueError("配置必须是 JSON 对象")
        for key in required:
            if not isinstance(settings.get(key), str) or not settings[key].strip():
                raise ValueError(f"配置项 {key} 必须是非空字符串")
        return run(settings, args.symbols, args.timeout, args.duration)
    except KeyboardInterrupt:
        print("已停止并关闭 API", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, TimeoutError) as exc:
        print(f"DEMO 未完成：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
