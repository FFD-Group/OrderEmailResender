from unittest.mock import MagicMock, Mock
import OrderEmailResender
import os
import pendulum
import requests
import unittest


class MockResponse:
    def __init__(self, json_data, status_code):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data


class TestOrderEmailResender(unittest.TestCase):
    def test_check_daylight_savings_time(self):
        """Test checking daylight savings time and how the function
        handles API availability or response changes."""

        ORDER_AGE_MINS = int(os.getenv("ORDER_AGE_MINS"))
        # Test API returns expected data
        requests.get = MagicMock(
            return_value=MockResponse({"isDayLightSavingActive": True}, 200)
        )
        OrderEmailResender.check_daylight_savings_time()
        self.assertEqual(
            OrderEmailResender.SYNC_PERIOD_TIME_STR,
            pendulum.now()
            .subtract(hours=1, minutes=ORDER_AGE_MINS)
            .to_datetime_string(),
        )
        requests.get.assert_called()

        # Test API returns unexpected data
        requests.get = MagicMock(return_value=MockResponse({"foo": "bar"}, 200))
        OrderEmailResender.check_daylight_savings_time()
        self.assertEqual(
            OrderEmailResender.SYNC_PERIOD_TIME_STR,
            pendulum.now()
            .subtract(hours=1, minutes=ORDER_AGE_MINS)
            .to_datetime_string(),
        )
        requests.get.assert_called()

        # Test API is unavailable
        requests.get = Mock(return_value=MockResponse({}, 500))
        requests.get.side_effect = requests.exceptions.ConnectionError()
        with self.assertRaises(requests.exceptions.ConnectionError):
            OrderEmailResender.check_daylight_savings_time()
        self.assertEqual(
            OrderEmailResender.SYNC_PERIOD_TIME_STR,
            pendulum.now()
            .subtract(hours=1, minutes=ORDER_AGE_MINS)
            .to_datetime_string(),
        )
        requests.get.assert_called()


if __name__ == "__main__":
    unittest.main()
