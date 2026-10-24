import unittest
from datetime import date, datetime

from daytrader.costs import ChargeSchedule, breakeven_move_pct, order_charges, round_trip_charges
from daytrader.market_calendar import IST, NSECalendar


class TestCosts(unittest.TestCase):
    def test_one_lakh_round_trip_matches_zerodha_calculator(self):
        ch = round_trip_charges(100_000, 100_000)
        d = ch.as_dict()
        self.assertEqual(d["brokerage"], 40.00)
        self.assertEqual(d["stt"], 25.00)
        self.assertEqual(d["exchange"], 6.14)
        self.assertEqual(d["sebi"], 0.20)
        self.assertEqual(d["gst"], 8.34)
        self.assertEqual(d["stamp"], 3.00)
        self.assertAlmostEqual(ch.total, 82.68, places=2)

    def test_small_order_uses_percent_brokerage_not_cap(self):
        self.assertAlmostEqual(order_charges("BUY", 10_000).brokerage, 3.0)

    def test_stt_only_on_sell_and_stamp_only_on_buy(self):
        self.assertEqual(order_charges("BUY", 50_000).stt, 0)
        self.assertEqual(order_charges("SELL", 50_000).stamp, 0)

    def test_breakeven(self):
        self.assertAlmostEqual(breakeven_move_pct(100_000), 0.08268, places=4)

    def test_custom_schedule_from_dict(self):
        s = ChargeSchedule.from_dict({"brokerage_cap": 0, "unknown_key": 5})
        self.assertEqual(order_charges("BUY", 100_000, s).brokerage, 0)

    def test_bad_side(self):
        with self.assertRaises(ValueError):
            order_charges("HOLD", 100)


class TestCalendar(unittest.TestCase):
    def setUp(self):
        self.cal = NSECalendar()

    def test_weekend_and_holidays(self):
        self.assertFalse(self.cal.is_trading_day(date(2026, 10, 24)))  # Saturday
        self.assertFalse(self.cal.is_trading_day(date(2026, 11, 10)))  # Diwali Balipratipada
        self.assertFalse(self.cal.is_trading_day(date(2026, 12, 25)))
        self.assertTrue(self.cal.is_trading_day(date(2026, 10, 23)))

    def test_next_trading_day_skips_weekend(self):
        self.assertEqual(self.cal.next_trading_day(date(2026, 10, 23)), date(2026, 10, 26))

    def test_market_hours(self):
        self.assertTrue(self.cal.is_market_open(datetime(2026, 10, 23, 9, 15, tzinfo=IST)))
        self.assertFalse(self.cal.is_market_open(datetime(2026, 10, 23, 15, 30, tzinfo=IST)))
        self.assertFalse(self.cal.is_market_open(datetime(2026, 10, 23, 9, 10, tzinfo=IST)))

    def test_holiday_year_known(self):
        self.assertTrue(self.cal.holiday_list_known(date(2026, 5, 1)))
        self.assertFalse(self.cal.holiday_list_known(date(2027, 5, 1)))


if __name__ == "__main__":
    unittest.main()
