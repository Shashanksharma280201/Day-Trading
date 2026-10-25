import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from daytrader.broker import Order, PaperBroker
from daytrader.broker.groww import GrowwBroker, GrowwClient, GrowwError, checksum, new_reference_id
from daytrader.engine import Engine, EngineConfig
from daytrader.risk import RiskConfig
from daytrader.server import ApprovalServer
from daytrader.strategies import OpeningRangeBreakout

from test_engine import orb_bars


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeGroww:
    """Records requests and answers like Groww's API."""

    def __init__(self, answers):
        self.answers = answers
        self.requests = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode()) if req.data else None
        self.requests.append((req.get_method(), req.full_url, dict(req.header_items()), body))
        for prefix, payload in self.answers:
            if prefix in req.full_url:
                return FakeResp(json.dumps({"status": "SUCCESS", "payload": payload}).encode())
        return FakeResp(json.dumps({"status": "FAILURE", "error": {"code": "GA004", "message": "nope"}}).encode())


class TestGrowwClient(unittest.TestCase):
    def test_checksum_and_reference(self):
        self.assertEqual(len(checksum("s", "1700000000")), 64)
        ref = new_reference_id()
        self.assertTrue(8 <= len(ref) <= 20)
        self.assertLessEqual(ref.count("-"), 2)

    def test_ltp_and_headers(self):
        fake = FakeGroww([("/v1/live-data/ltp", {"NSE_INFY": 1512.4, "NSE_TCS": 3200})])
        c = GrowwClient("tok", opener=fake)
        self.assertEqual(c.ltp(["INFY", "TCS"]), {"INFY": 1512.4, "TCS": 3200.0})
        _, url, headers, _ = fake.requests[0]
        self.assertIn("exchange_symbols=NSE_INFY%2CNSE_TCS", url)
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(headers["X-api-version"], "1.0")

    def test_failure_raises(self):
        c = GrowwClient("tok", opener=FakeGroww([]))
        with self.assertRaises(GrowwError):
            c.positions()

    def test_no_token(self):
        with self.assertRaises(GrowwError):
            GrowwClient(opener=FakeGroww([])).ltp(["INFY"])

    def test_totp_login_sets_token(self):
        fake = FakeGroww([("/v1/token/api/access", {"token": "abc", "expiry": "2026-10-27T00:30:00Z"})])
        c = GrowwClient(opener=fake)
        c.login_with_totp("KEY", "123456")
        self.assertEqual(c.access_token, "abc")
        self.assertEqual(fake.requests[0][3], {"key_type": "totp", "totp": "123456"})

    def test_candles_parse(self):
        fake = FakeGroww([("/v1/historical/candles", {"candles": [["2026-10-23 09:15:00", 1, 2, 0.5, 1.5, 100, None]]})])
        from datetime import datetime
        bars = GrowwClient("t", opener=fake).candles("INFY", datetime(2026, 10, 23, 9, 15), datetime(2026, 10, 23, 9, 20))
        self.assertEqual(bars[0].close, 1.5)
        self.assertEqual(bars[0].timestamp.hour, 9)


class TestGrowwBroker(unittest.TestCase):
    def test_market_order_becomes_protected_limit(self):
        body = GrowwBroker.order_body(Order("INFY", "BUY", 10, market_protection_pct=1.0), ltp=1500)
        self.assertEqual(body["order_type"], "LIMIT")
        self.assertEqual(body["price"], 1515.0)
        self.assertEqual(body["product"], "MIS")
        self.assertEqual(body["segment"], "CASH")

    def test_sl_m_body(self):
        body = GrowwBroker.order_body(Order("INFY", "SELL", 10, order_type="SL-M", trigger=1490))
        self.assertEqual(body["order_type"], "SL_M")
        self.assertEqual(body["trigger_price"], 1490)

    def test_place_and_fill(self):
        fake = FakeGroww([("/v1/order/create", {"groww_order_id": "G1", "order_status": "NEW"}),
                          ("/v1/order/detail/G1", {"order_status": "EXECUTED", "average_fill_price": 1501.2})])
        b = GrowwBroker(GrowwClient("t", opener=fake), sleep=lambda s: None)
        res = b.place_order(Order("INFY", "BUY", 1), ltp=1500)
        self.assertTrue(res.ok)
        self.assertEqual(res.fill_price, 1501.2)

    def test_market_without_price_refused(self):
        b = GrowwBroker(GrowwClient("t", opener=FakeGroww([])))
        self.assertFalse(b.place_order(Order("INFY", "BUY", 1)).ok)


class TestServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = Engine(OpeningRangeBreakout(), RiskConfig(capital=100_000, max_position_pct=50),
                             PaperBroker(100_000, slippage_bps=0), EngineConfig(state_dir=self.tmp.name))
        self.server = ApprovalServer(self.engine, "secret-token", port=0)
        self.server.start()
        self.base = "http://%s:%d" % self.server.address

    def tearDown(self):
        self.server.stop()
        self.tmp.cleanup()

    def call(self, method, path, body=None, token="secret-token"):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health_needs_no_token(self):
        with urllib.request.urlopen(self.base + "/api/health") as r:
            self.assertEqual(json.loads(r.read())["mode"], "paper")

    def test_wrong_token(self):
        self.assertEqual(self.call("GET", "/api/state", token="bad")[0], 401)

    def test_approve_over_http(self):
        for b in orb_bars():
            self.engine.on_bar(b)
        code, state = self.call("GET", "/api/state")
        pid = state["proposals"][0]["id"]
        code, res = self.call("POST", f"/api/proposals/{pid}/approve", {"device": "android"})
        self.assertEqual(code, 200)
        self.assertTrue(res["ok"])
        self.assertEqual(res["proposal"]["decided_by"], "android")
        code, res = self.call("POST", f"/api/proposals/{pid}/approve", {"device": "island"})
        self.assertFalse(res["ok"])

    def test_kill_over_http(self):
        code, res = self.call("POST", "/api/kill", {"device": "island", "reason": "done"})
        self.assertTrue(res["killed"])
        self.assertTrue(self.engine.killed)

    def test_event_stream(self):
        req = urllib.request.Request(self.base + "/api/events?token=secret-token")
        resp = urllib.request.urlopen(req, timeout=5)
        lines = []

        def read():
            for raw in resp:
                lines.append(raw.decode())
                if any(l.startswith("event: proposal\n") for l in lines):
                    break

        t = threading.Thread(target=read, daemon=True)
        t.start()
        for b in orb_bars():
            self.engine.on_bar(b)
        t.join(5)
        resp.close()
        self.assertIn("event: state\n", lines)
        self.assertIn("event: proposal\n", lines)


if __name__ == "__main__":
    unittest.main()
