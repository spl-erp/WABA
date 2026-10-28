"""Run without a site:  python -m unittest waba.tests.test_window"""

import datetime
import unittest

from waba.rules import window

T0 = datetime.datetime(2026, 10, 28, 9, 0, 0)


class TestWindow(unittest.TestCase):
	def test_never_wrote_means_closed(self):
		self.assertFalse(window.is_window_open(None, T0))
		self.assertIsNone(window.window_expires_at(None))
		self.assertEqual(window.seconds_left(None, T0), 0)

	def test_open_for_24_hours_after_the_last_inbound(self):
		self.assertTrue(window.is_window_open(T0, T0 + datetime.timedelta(hours=23, minutes=59)))
		self.assertEqual(window.window_expires_at(T0), T0 + datetime.timedelta(hours=24))

	def test_closes_exactly_at_24_hours(self):
		self.assertFalse(window.is_window_open(T0, T0 + datetime.timedelta(hours=24)))
		self.assertFalse(window.is_window_open(T0, T0 + datetime.timedelta(days=3)))

	def test_seconds_left(self):
		self.assertEqual(window.seconds_left(T0, T0 + datetime.timedelta(hours=23)), 3600)
		self.assertEqual(window.seconds_left(T0, T0 + datetime.timedelta(hours=24)), 0)
		self.assertEqual(window.seconds_left(T0, T0 + datetime.timedelta(hours=30)), 0)

	def test_a_newer_inbound_reopens_it(self):
		later = T0 + datetime.timedelta(hours=30)
		newer = later - datetime.timedelta(hours=1)
		self.assertFalse(window.is_window_open(T0, later))
		self.assertTrue(window.is_window_open(newer, later))


if __name__ == "__main__":
	unittest.main()
