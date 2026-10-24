import unittest
from datetime import date, time

from daytrader.broker import Order, PaperBroker
from daytrader.risk import OrderThrottle, RiskConfig, RiskManager


class TestRisk(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=0.5,
                                         max_position_pct=20, daily_loss_limit_pct=2,
                                         max_trades_per_day=2, max_open_positions=1))
        self.rm.start_day(date(2026, 10, 23))
        self.t = time(10, 0)

    def test_sizing_by_risk(self):
        # Rs 500 risk / Rs 10 per share = 50 shares; 50 x 300 = 15,000 < 20,000 cap
        d = self.rm.check_entry("INFY", "BUY", self.t, 300, 290)
        self.assertTrue(d.ok)
        self.assertEqual(d.qty, 50)

    def test_sizing_capped_by_position_value(self):
        # risk allows 500 shares but 20% of capital at Rs 1000 is 20 shares
        self.assertEqual(self.rm.check_entry("TCS", "BUY", self.t, 1000, 999).qty, 20)

    def test_time_windows(self):
        self.assertFalse(self.rm.check_entry("A", "BUY", time(9, 16), 100, 99).ok)
        self.assertFalse(self.rm.check_entry("A", "BUY", time(14, 50), 100, 99).ok)

    def test_fno_blocked_and_equity_ending_in_ce_allowed(self):
        self.assertFalse(self.rm.check_entry("NIFTY26OCT25000CE", "BUY", self.t, 100, 90).ok)
        self.assertFalse(self.rm.check_entry("BANKNIFTY26OCTFUT", "BUY", self.t, 100, 90).ok)
        self.assertTrue(self.rm.check_entry("RELIANCE", "BUY", self.t, 100, 99).ok)

    def test_stop_side_validation(self):
        self.assertFalse(self.rm.check_entry("A", "BUY", self.t, 100, 101).ok)
        self.assertFalse(self.rm.check_entry("A", "SELL", self.t, 100, 99).ok)

    def test_daily_loss_limit_halts(self):
        self.rm.on_entry("A")
        self.rm.on_exit("A", -2_000)
        self.assertTrue(self.rm.halted)
        self.assertIn("halted", self.rm.check_entry("B", "BUY", self.t, 100, 99).reason)

    def test_trade_and_position_caps(self):
        self.rm.on_entry("A")
        self.assertIn("max open", self.rm.check_entry("B", "BUY", self.t, 100, 99).reason)
        self.rm.on_exit("A", 10)
        self.rm.on_entry("B")
        self.rm.on_exit("B", 10)
        self.assertIn("max trades", self.rm.check_entry("C", "BUY", self.t, 100, 99).reason)

    def test_config_refuses_sebi_threshold(self):
        with self.assertRaises(ValueError):
            RiskConfig(max_orders_per_second=10).validate()


class TestThrottle(unittest.TestCase):
    def test_throttle_waits(self):
        clock = [0.0]
        slept = []

        def sleep(s):
            slept.append(s)
            clock[0] += s

        th = OrderThrottle(3, clock=lambda: clock[0], sleep=sleep)
        for _ in range(4):
            th.wait()
        self.assertEqual(len(slept), 1)
        self.assertGreaterEqual(clock[0], 1.0)


class TestPaperBroker(unittest.TestCase):
    def test_round_trip_pnl_and_charges(self):
        b = PaperBroker(100_000, slippage_bps=0)
        b.place_order(Order("INFY", "BUY", 10), ltp=1000)
        b.place_order(Order("INFY", "SELL", 10), ltp=1010)
        p = b.positions()["INFY"]
        self.assertEqual(p["qty"], 0)
        self.assertAlmostEqual(p["realized"], 100.0)
        self.assertGreater(b.total_charges, 0)
        self.assertAlmostEqual(b.cash, 100_000 + 100 - b.total_charges, places=6)

    def test_short_then_cover(self):
        b = PaperBroker(100_000, slippage_bps=0)
        b.place_order(Order("SBIN", "SELL", 5), ltp=800)
        b.place_order(Order("SBIN", "BUY", 5), ltp=790)
        self.assertAlmostEqual(b.positions()["SBIN"]["realized"], 50.0)

    def test_market_order_needs_protection(self):
        with self.assertRaises(ValueError):
            Order("A", "BUY", 1, market_protection_pct=0).validate()

    def test_square_off_all(self):
        b = PaperBroker(100_000, slippage_bps=0)
        b.place_order(Order("A", "BUY", 3), ltp=100)
        b.square_off_all({"A": 101})
        self.assertEqual(b.positions()["A"]["qty"], 0)


if __name__ == "__main__":
    unittest.main()
