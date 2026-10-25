import tempfile
import unittest
from datetime import datetime

from daytrader.broker import PaperBroker
from daytrader.broker.base import Broker, OrderResult
from daytrader.engine import Engine, EngineConfig
from daytrader.market_calendar import IST
from daytrader.risk import RiskConfig
from daytrader.strategies import OpeningRangeBreakout

from helpers import DAY, bar


def orb_bars():
    """Range 99 to 101, breakout close 101.5 at the 09:30 bar."""
    bars = [bar(f"09:{15 + i}", 100, 101, 99, 100) for i in range(15)]
    bars.append(bar("09:30", 100.5, 101.6, 100.4, 101.5))
    return bars


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.events = []
        self.engine = self.make()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, **risk):
        cfg = dict(capital=100_000, max_position_pct=50)
        cfg.update(risk)
        e = Engine(OpeningRangeBreakout(), RiskConfig(**cfg), PaperBroker(100_000, slippage_bps=0),
                   EngineConfig(approval_ttl=60, max_drift_pct=0.3, state_dir=self.tmp.name),
                   clock=self.clock)
        e.subscribe(self.events.append)
        return e

    def feed(self, bars):
        for b in bars:
            self.engine.on_bar(b)

    def pending(self):
        return [p for p in self.engine.proposals.values() if p.status == "pending"]

    def test_signal_becomes_proposal_not_order(self):
        self.feed(orb_bars())
        self.assertEqual(len(self.pending()), 1)
        self.assertEqual(self.engine.positions, {})
        p = self.pending()[0]
        self.assertEqual((p.symbol, p.side, p.stop), ("TEST", "BUY", 99))
        self.assertGreater(p.qty, 0)
        self.assertIn("proposal", [e["type"] for e in self.events])

    def test_approve_opens_position(self):
        self.feed(orb_bars())
        pid = self.pending()[0].id
        res = self.engine.approve(pid, by="island")
        self.assertTrue(res["ok"], res)
        self.assertIn("TEST", self.engine.positions)
        self.assertEqual(self.engine.proposals[pid].decided_by, "island")

    def test_second_approval_refused(self):
        self.feed(orb_bars())
        pid = self.pending()[0].id
        self.engine.approve(pid, by="island")
        res = self.engine.approve(pid, by="android")
        self.assertFalse(res["ok"])
        self.assertIn("already placed", res["error"])

    def test_reject(self):
        self.feed(orb_bars())
        pid = self.pending()[0].id
        self.assertEqual(self.engine.reject(pid)["proposal"]["status"], "rejected")
        self.assertEqual(self.engine.positions, {})

    def test_no_answer_expires(self):
        self.feed(orb_bars())
        pid = self.pending()[0].id
        self.clock.t += 61
        self.engine.on_prices({"TEST": 101.5}, datetime(2026, 10, 23, 9, 31, 10, tzinfo=IST))
        self.assertEqual(self.engine.proposals[pid].status, "expired")
        self.assertFalse(self.engine.approve(pid)["ok"])
        self.assertEqual(self.engine.positions, {})

    def test_stale_price_refused(self):
        self.feed(orb_bars())
        pid = self.pending()[0].id
        self.engine.on_prices({"TEST": 103.0}, datetime(2026, 10, 23, 9, 31, 5, tzinfo=IST))
        res = self.engine.approve(pid)
        self.assertEqual(res["proposal"]["status"], "stale")
        self.assertEqual(self.engine.positions, {})

    def test_risk_rechecked_on_approve(self):
        self.feed(orb_bars())
        pid = self.pending()[0].id
        self.engine.on_prices({"TEST": 101.5}, datetime(2026, 10, 23, 14, 50, tzinfo=IST))  # past 14:45
        res = self.engine.approve(pid)
        self.assertEqual(res["proposal"]["status"], "rejected")
        self.assertIn("after 14:45", res["error"])

    def test_stop_exit_is_automatic(self):
        self.feed(orb_bars())
        self.engine.approve(self.pending()[0].id)
        self.engine.on_prices({"TEST": 98.9}, datetime(2026, 10, 23, 9, 35, tzinfo=IST))
        self.assertEqual(self.engine.positions, {})
        tr = self.engine.trades[0]
        self.assertEqual(tr.exit_reason, "stop")
        self.assertLess(tr.net_pnl, 0)

    def test_target_and_square_off(self):
        self.feed(orb_bars())
        self.engine.approve(self.pending()[0].id)
        self.engine.on_prices({"TEST": 102.0}, datetime(2026, 10, 23, 15, 10, tzinfo=IST))
        self.assertEqual(self.engine.trades[0].exit_reason, "square_off")

    def test_kill_switch_blocks_and_flattens(self):
        self.feed(orb_bars())
        self.engine.approve(self.pending()[0].id)
        self.engine.kill("enough for today", flatten=True)
        self.assertEqual(self.engine.positions, {})
        self.assertEqual(self.engine.trades[0].exit_reason, "kill_switch")
        self.assertTrue(self.engine.summary()["killed"])

    def test_kill_rejects_pending(self):
        self.feed(orb_bars())
        pid = self.pending()[0].id
        self.engine.kill()
        self.assertEqual(self.engine.proposals[pid].status, "rejected")

    def test_daily_loss_limit_flattens(self):
        self.engine = self.make(daily_loss_limit_pct=0.1)  # Rs 100
        self.feed(orb_bars())
        self.engine.approve(self.pending()[0].id)
        self.engine.on_prices({"TEST": 99.5}, datetime(2026, 10, 23, 9, 40, tzinfo=IST))
        self.assertTrue(self.engine.killed)
        self.assertEqual(self.engine.positions, {})

    def test_new_day_resets_kill(self):
        self.feed(orb_bars())
        self.engine.kill()
        self.engine.on_prices({"TEST": 100}, datetime(2026, 10, 26, 9, 15, tzinfo=IST))
        self.assertFalse(self.engine.killed)

    def test_state_snapshot(self):
        self.feed(orb_bars())
        s = self.engine.state()
        self.assertEqual(s["mode"], "paper")
        self.assertEqual(s["pending_approvals"], 1)
        self.assertEqual(len(s["proposals"]), 1)
        self.assertGreater(s["proposals"][0]["seconds_left"], 0)

    def test_audit_log_written(self):
        import os
        self.feed(orb_bars())
        files = os.listdir(self.tmp.name)
        self.assertTrue(any(f.startswith("audit-") for f in files))

    def test_paper_mode_refuses_live_broker(self):
        class Live(Broker):
            is_live = True
            def place_order(self, order, ltp=None): return OrderResult(True)
            def cancel_order(self, oid): return OrderResult(True)
            def positions(self): return {}
        with self.assertRaises(ValueError):
            Engine(OpeningRangeBreakout(), RiskConfig(), Live(), EngineConfig(state_dir=self.tmp.name))


class TestLiveEngineStops(unittest.TestCase):
    def test_live_entry_places_broker_stop(self):
        placed = []

        class FakeLive(Broker):
            is_live = True
            def place_order(self, order, ltp=None):
                placed.append(order)
                return OrderResult(True, f"G{len(placed)}", "OPEN" if order.order_type == "SL-M" else "EXECUTED",
                                   None if order.order_type == "SL-M" else ltp)
            def cancel_order(self, oid): return OrderResult(True, oid, "CANCELLED")
            def positions(self): return {"TEST": {"qty": 1}}

        with tempfile.TemporaryDirectory() as d:
            e = Engine(OpeningRangeBreakout(), RiskConfig(capital=100_000, max_position_pct=50), FakeLive(),
                       EngineConfig(mode="live", state_dir=d))
            for b in orb_bars():
                e.on_bar(b)
            pid = next(iter(e.proposals))
            self.assertTrue(e.approve(pid)["ok"])
            self.assertEqual(placed[1].order_type, "SL-M")
            self.assertEqual(placed[1].trigger, 99)
            self.assertEqual(e.positions["TEST"].stop_order_id, "G2")


if __name__ == "__main__":
    unittest.main()
