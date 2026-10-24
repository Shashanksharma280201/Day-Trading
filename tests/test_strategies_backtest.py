import unittest
from datetime import date, time

from daytrader.backtest import Backtester
from daytrader.data import load_csv, synthetic_bars, write_csv
from daytrader.risk import RiskConfig
from daytrader.strategies import OpeningRangeBreakout, VWAPCross, build

from helpers import DAY, bar, flat_bars

RISK = RiskConfig(capital=100_000, no_entry_before="09:20", no_entry_after="14:45",
                  square_off_at="15:10", max_position_pct=50)


def orb_day(after_breakout):
    """Range 99 to 101 (2%), breakout close 101.5 at 09:30, then `after_breakout` bars."""
    bars = [bar(f"09:{15 + i}", 100, 101, 99, 100) for i in range(15)]
    bars.append(bar("09:30", 100.5, 101.6, 100.4, 101.5))
    return bars + after_breakout


class TestORB(unittest.TestCase):
    def test_long_signal_after_range(self):
        s = OpeningRangeBreakout(range_minutes=15, reward_risk=2)
        s.start_day(DAY)
        sigs = [s.on_bar(b) for b in orb_day([])]
        sig = sigs[-1]
        self.assertIsNotNone(sig)
        self.assertEqual(sig.side, "BUY")
        self.assertEqual(sig.stop, 99)
        self.assertAlmostEqual(sig.target, 101.5 + 2 * 2.5)
        self.assertTrue(all(x is None for x in sigs[:-1]))

    def test_one_signal_per_day(self):
        s = OpeningRangeBreakout(max_signals_per_day=1)
        s.start_day(DAY)
        out = [s.on_bar(b) for b in orb_day([bar("09:31", 101.5, 102, 101.4, 101.9)])]
        self.assertEqual(sum(1 for x in out if x), 1)

    def test_range_too_narrow_skipped(self):
        s = OpeningRangeBreakout(min_range_pct=5)
        s.start_day(DAY)
        self.assertTrue(all(s.on_bar(b) is None for b in orb_day([])))


class TestVWAP(unittest.TestCase):
    def test_cross_above(self):
        s = VWAPCross(warmup_minutes=5, stop_pct=0.5)
        s.start_day(DAY)
        bars = [bar(f"09:{15 + i}", 100, 100, 100, 100, v=1000) for i in range(5)]
        bars.append(bar("09:20", 100, 100, 99, 99, v=1000))   # below
        bars.append(bar("09:21", 99, 101, 99, 101, v=1000))   # crosses above
        out = [s.on_bar(b) for b in bars]
        self.assertIsNotNone(out[-1])
        self.assertEqual(out[-1].side, "BUY")


class TestBacktester(unittest.TestCase):
    def run_day(self, after):
        bt = Backtester(OpeningRangeBreakout(), RISK, slippage_bps=0)
        return bt.run(orb_day(after))

    def test_entry_fills_next_bar_open_and_hits_target(self):
        res = self.run_day([bar("09:31", 101.6, 107, 101.5, 106.5)])
        self.assertEqual(len(res.trades), 1)
        t = res.trades[0]
        self.assertEqual(t.entry_price, 101.6)    # next bar's open, not the signal close
        self.assertEqual(t.exit_reason, "target")
        self.assertEqual(t.exit_price, 106.5)     # target = 101.5 + 2 x 2.5
        self.assertLess(t.net_pnl, t.gross_pnl)   # charges always paid

    def test_stop_assumed_before_target_in_same_bar(self):
        res = self.run_day([bar("09:31", 101.6, 107, 98, 100)])
        self.assertEqual(res.trades[0].exit_reason, "stop")

    def test_gap_through_stop_fills_at_open(self):
        res = self.run_day([bar("09:31", 101.6, 101.7, 101.5, 101.6),
                            bar("09:32", 97, 97.5, 96, 97)])
        self.assertEqual(res.trades[0].exit_reason, "stop")
        self.assertEqual(res.trades[0].exit_price, 97)

    def test_square_off(self):
        after = [bar("09:31", 101.6, 101.7, 101.5, 101.6)] + flat_bars("09:32", "15:30", 102)
        res = self.run_day(after)
        t = res.trades[0]
        self.assertEqual(t.exit_reason, "square_off")
        self.assertEqual(t.exit_time.time(), time(15, 10))

    def test_no_entry_window(self):
        risk = RiskConfig(capital=100_000, no_entry_before="10:00", max_position_pct=50)
        bt = Backtester(OpeningRangeBreakout(), risk, slippage_bps=0)
        res = bt.run(orb_day([bar("09:31", 101.6, 107, 101.5, 106.5)]))
        self.assertEqual(len(res.trades), 0)
        self.assertEqual(len(res.skipped), 1)

    def test_holiday_data_ignored(self):
        bars = [bar("09:15", 100, 101, 99, 100, d=date(2026, 11, 10))]
        res = Backtester(OpeningRangeBreakout(), RISK).run(bars)
        self.assertEqual(res.days_tested, 0)
        self.assertEqual(res.non_trading_days_in_data, [date(2026, 11, 10)])

    def test_random_walk_has_no_edge_after_costs(self):
        bars = synthetic_bars(["AAA", "BBB"], date(2026, 7, 1), 30, seed=3)
        for name in ("orb", "vwap"):
            res = Backtester(build(name), RiskConfig(capital=100_000)).run(bars)
            total_costs = sum(t.charges for t in res.trades)
            self.assertGreater(total_costs, 0)
            self.assertTrue(all(t.exit_time.time() <= time(15, 10) for t in res.trades))

    def test_csv_round_trip(self):
        import tempfile, os
        bars = synthetic_bars(["AAA"], date(2026, 7, 1), 1, seed=1)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "b.csv")
            write_csv(bars, p)
            back = load_csv(p)
        self.assertEqual(len(back), len(bars))
        self.assertEqual(back[0].symbol, "AAA")


if __name__ == "__main__":
    unittest.main()
