"""底层 CTP API：持续行情与单次价格触发 SimNow 买入开仓。"""

import argparse
import json
import os
import sys
from importlib.metadata import version
from math import isfinite
from pathlib import Path
from threading import Event
from time import monotonic, sleep


HERE = Path(__file__).resolve().parent
DEFAULT_SYMBOLS = ["rb2701", "ag2612", "au2612"]


def valid_price(value):
    return isinstance(value, (int, float)) and isfinite(value) and 0 < value < 1e100


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


def create_clients(settings, trade_symbol=None):
    # 延迟导入：--help、配置检查和离线测试不要求加载原生 SDK。
    from vnpy_ctp.api import MdApi, TdApi

    login = {"UserID": settings["userid"], "Password": settings["password"],
             "BrokerID": settings["brokerid"]}

    class DemoTdApi(TdApi):
        def __init__(self):
            super().__init__()
            self.reqid, self.error, self.ready = 0, "", Event()
            self.contract, self.order_ref, self.order_key = {}, "", None
            self.trading_day, self.frontid, self.sessionid = "", 0, 0
            self.attempted, self.order_done, self.all_traded = False, False, False
            self.filled, self.tradeids, self.completed = 0, set(), Event()
            self.journal = HERE / "runtime" / "single-order.json"
            self.record = {}

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
                self.frontid, self.sessionid = data.get("FrontID", 0), data.get("SessionID", 0)
                self.trading_day = data.get("TradingDay", "")
                if not self.attempted:
                    self.order_ref = str(int(data.get("MaxOrderRef", "").strip() or "0") + 1)
                if trade_symbol:
                    send_request(self, self.reqSettlementInfoConfirm,
                                 {"BrokerID": settings["brokerid"], "InvestorID": settings["userid"]},
                                 "结算确认")
                else:
                    self.ready.set()

        def onRspSettlementInfoConfirm(self, data, error, reqid, last):
            if check_response(self, "结算确认", error):
                print("结算确认成功，查询交易合约", flush=True)
                send_request(self, self.reqQryInstrument, {"InstrumentID": trade_symbol}, "合约查询")

        def onRspQryInstrument(self, data, error, reqid, last):
            if not check_response(self, "合约查询", error):
                return
            if data.get("InstrumentID") == trade_symbol:
                self.contract = data.copy()
            if last:
                if not valid_price(self.contract.get("PriceTick")):
                    fail(self, "找不到有效交易合约信息")
                else:
                    print(f"交易准备完成：{trade_symbol}", flush=True)
                    self.ready.set()

        def save_record(self, **updates):
            self.record.update(updates)
            self.journal.write_text(json.dumps(self.record, ensure_ascii=False, indent=2) + "\n")

        def try_buy(self, tick, threshold):
            if self.attempted or not self.ready.is_set() or self.error or not tick:
                return
            prices = [tick.get(k) for k in ("LastPrice", "BidPrice1", "AskPrice1",
                                          "LowerLimitPrice", "UpperLimitPrice")]
            if not all(valid_price(p) for p in prices):
                return
            last, bid, ask, lower, upper = prices
            if (last <= threshold or not lower <= bid <= ask <= upper or not lower <= last <= upper
                    or tick.get("TradingDay") != self.trading_day
                    or tick.get("AskVolume1", 0) < 1 or tick.get("BidVolume1", 0) < 1):
                return
            step = self.contract["PriceTick"]
            price = round(ask / step) * step
            if abs(price - ask) > step * 1e-6:
                return
            if not self.contract.get("IsTrading") or not (
                    self.contract.get("MinLimitOrderVolume", 1) <= 1
                    <= self.contract.get("MaxLimitOrderVolume", 1)):
                fail(self, "交易合约当前不允许 1 手限价交易")
                return
            self.order_key = (self.frontid, self.sessionid, self.order_ref)
            self.record = {"state": "attempted", "symbol": trade_symbol, "order_ref": self.order_ref,
                           "front_id": self.frontid, "session_id": self.sessionid,
                           "trading_day": self.trading_day, "threshold": threshold,
                           "trigger_price": last, "limit_price": price, "volume": 1, "filled": 0}
            # 先持久化并独占创建，避免重启/多个进程重复触发同一次作业。
            with self.journal.open("x") as file:
                json.dump(self.record, file, ensure_ascii=False, indent=2)
            self.attempted = True
            print(f"价格触发：{trade_symbol} 最新价 {last} > {threshold}；限价 {price} 买开 1 手", flush=True)
            request = {"BrokerID": settings["brokerid"], "UserID": settings["userid"],
                       "InvestorID": settings["userid"], "InstrumentID": trade_symbol,
                       "ExchangeID": self.contract["ExchangeID"], "OrderRef": self.order_ref,
                       "LimitPrice": price, "VolumeTotalOriginal": 1,
                       "OrderPriceType": "2", "Direction": "0", "CombOffsetFlag": "0",
                       "CombHedgeFlag": "1", "ContingentCondition": "1", "ForceCloseReason": "0",
                       "IsAutoSuspend": 0, "TimeCondition": "3", "VolumeCondition": "1", "MinVolume": 1}
            send_request(self, self.reqOrderInsert, request, "仿真下单")
            if self.error:
                self.save_record(state="send_failed", error=self.error)

        def own_order(self, data):
            return (self.attempted and data.get("OrderRef") == self.order_ref
                    and data.get("InstrumentID") == trade_symbol)

        def onRspOrderInsert(self, data, error, reqid, last):
            if self.own_order(data) and not check_response(self, "仿真下单", error):
                self.order_done = True
                self.save_record(state="rejected", error=self.error)

        def onErrRtnOrderInsert(self, data, error):
            self.onRspOrderInsert(data, error, 0, True)

        def onRtnOrder(self, data):
            if not self.own_order(data) or (data.get("FrontID"), data.get("SessionID"),
                                          data.get("OrderRef")) != self.order_key:
                return
            status = data["OrderStatus"]
            self.order_done = status in ("0", "2", "4", "5")
            self.all_traded = status == "0"
            print(f"订单回报：状态 {status}，累计成交 {data.get('VolumeTraded', 0)}，"
                  f"{data.get('StatusMsg', '')}", flush=True)
            self.save_record(order_status=status, order_traded=data.get("VolumeTraded", 0))
            if status in ("2", "4", "5"):
                fail(self, f"委托结束但未全部成交：{data.get('StatusMsg', status)}")
                self.save_record(state="unfilled", error=self.error)
            self.check_completed()

        def onRtnTrade(self, data):
            if not self.own_order(data):
                return
            key = (data["ExchangeID"], data["TradeID"], data["TradeDate"])
            if key in self.tradeids:
                return
            self.tradeids.add(key)
            self.filled += data["Volume"]
            print(f"成交回报：{trade_symbol} 买开 {data['Volume']} 手，成交价 {data['Price']}", flush=True)
            self.save_record(filled=self.filled, trade_price=data["Price"], trade_time=data["TradeTime"])
            self.check_completed()

        def check_completed(self):
            if self.all_traded and self.filled == 1 and not self.completed.is_set():
                self.save_record(state="completed")
                self.completed.set()
                print("仿真闭环完成：订单全部成交且收到 1 手成交回报；继续打印行情", flush=True)

        def cancel_pending(self):
            if self.attempted and not self.order_done and self.ready.is_set() and not self.error:
                print("退出前请求撤销尚未结束的委托", flush=True)
                send_request(self, self.reqOrderAction,
                             {"BrokerID": settings["brokerid"], "InvestorID": settings["userid"],
                              "InstrumentID": trade_symbol, "ExchangeID": self.contract["ExchangeID"],
                              "OrderRef": self.order_ref, "FrontID": self.order_key[0],
                              "SessionID": self.order_key[1], "ActionFlag": "0"}, "撤单")
                until = monotonic() + 3
                while not self.order_done and monotonic() < until:
                    sleep(0.1)
                if not self.order_done:
                    print("尚未确认委托结束，请核对本地交易记录与柜台", flush=True)

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
            self.latest, self.received = {}, {}

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
            self.latest[data["InstrumentID"]] = data.copy()
            self.received[data["InstrumentID"]] = monotonic()
            fields = ("InstrumentID", "TradingDay", "ActionDay", "UpdateTime",
                      "UpdateMillisec", "LastPrice", "BidPrice1", "AskPrice1", "Volume")
            values = {k: data.get(k) for k in fields}
            for key in ("LastPrice", "BidPrice1", "AskPrice1"):
                if not valid_price(values[key]):
                    values[key] = None
            print("行情 " + json.dumps(values,
                                      ensure_ascii=False), flush=True)
            self.first_tick.set()

        def onFrontDisconnected(self, reason):
            self.ready.clear()
            self.first_tick.clear()
            self.latest.clear()
            self.received.clear()
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


def run(settings, symbols, timeout, duration, trade_symbol=None, threshold=None):
    # 包入口间接导入 vnpy；隔离其 .vntrader 文件，避免读取用户其他交易配置。
    runtime = HERE / "runtime"
    (runtime / ".vntrader").mkdir(parents=True, exist_ok=True)
    if trade_symbol and (runtime / "single-order.json").exists():
        raise RuntimeError("已有单次交易记录；为避免重复下单，请运行不带 --trade 的行情模式")
    previous_cwd = Path.cwd()
    started = []
    try:
        os.chdir(runtime)
        td, md = create_clients(settings, trade_symbol)
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
            args = (str(folder) + os.sep, False) if new_api else (str(folder) + os.sep,)
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
            if (trade_symbol and md.ready.is_set()
                    and monotonic() - md.received.get(trade_symbol, float("-inf")) <= 3):
                td.try_buy(md.latest.get(trade_symbol), threshold)
            sleep(0.1)
        if trade_symbol and not td.completed.is_set():
            raise RuntimeError("限时检查未完成仿真成交闭环；不自动重新下单")
        return 0
    finally:
        # 必须在主线程关闭；原生 exit 会等待回调线程结束。
        if started and trade_symbol:
            td.cancel_pending()
        for api in reversed(started):
            api.exit()
        os.chdir(previous_cwd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "config.local.json")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="CTP 合约代码，无交易所后缀")
    parser.add_argument("--timeout", type=float, default=0, help="每个启动阶段的超时秒数；0 表示持续等待")
    parser.add_argument("--duration", type=float, default=0, help="首条行情后运行秒数；0 表示持续运行")
    parser.add_argument("--trade", action="store_true", help="启用单次 SimNow 买入开仓 1 手")
    parser.add_argument("--trade-symbol", default="rb2701")
    parser.add_argument("--threshold", type=float, help="最新价严格大于此值才下单")
    args = parser.parse_args(argv)
    if args.timeout < 0 or args.duration < 0:
        parser.error("timeout 和 duration 不能小于 0")
    if args.trade and (not valid_price(args.threshold) or args.trade_symbol not in args.symbols):
        parser.error("交易模式须提供有效 --threshold，且 --trade-symbol 必须在订阅列表中")
    if args.threshold is not None and not args.trade:
        parser.error("使用 --threshold 时须同时提供 --trade")
    try:
        settings = json.loads(args.config.read_text())
        required = ("userid", "password", "brokerid", "td_address", "md_address", "appid", "auth_code")
        if not isinstance(settings, dict):
            raise ValueError("配置必须是 JSON 对象")
        for key in required:
            if not isinstance(settings.get(key), str) or not settings[key].strip():
                raise ValueError(f"配置项 {key} 必须是非空字符串")
        if args.trade:
            if (settings["brokerid"] != "9999" or settings["appid"] != "simnow_client_test"
                    or settings["td_address"] != "tcp://182.254.243.31:30001"
                    or settings["md_address"] != "tcp://182.254.243.31:30011"):
                raise ValueError("本作业下单模式仅允许已验证的 SimNow 前置配置")
            return run(settings, args.symbols, args.timeout, args.duration,
                       args.trade_symbol, args.threshold)
        return run(settings, args.symbols, args.timeout, args.duration)
    except KeyboardInterrupt:
        print("已停止并关闭 API", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, TimeoutError) as exc:
        print(f"DEMO 未完成：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
