import io
from unittest.mock import MagicMock, Mock
import OrderEmailResender
import os
import pendulum
import random
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

    def test_fetch_unsent_orders(self):
        """Test fetching unsent orders from the Magento API."""

        # Test API returns data with unsent orders
        mock_unsent_order_json = {"items": [], "total_count": 0}
        for _ in range(0, random.randint(1, 30)):
            mock_unsent_order_json["items"].append(
                {
                    "email_sent": 0,
                    "entity_id": random.randint(10_000, 99_999),
                    "increment_id": "60000"
                    + str(random.randint(10_000, 99_999)),
                    "status": random.choice(
                        ["processing", "new", "pending_payment", "complete"]
                    ),
                    "status_histories": [
                        {
                            "comment": 'Captured amount of £1,234.56 online. Transaction ID: "111"'
                            + str(random.randint(10_000_000, 99_000_000))
                        }
                    ],
                }
            )
        mock_unsent_order_json["total_count"] = len(
            mock_unsent_order_json["items"]
        )
        requests.get = MagicMock(
            return_value=MockResponse(mock_unsent_order_json, 200)
        )
        unsent_orders = OrderEmailResender.fetch_unsent_orders()
        self.assertIsInstance(unsent_orders, list)
        requests.get.assert_called()

        # Test API returns data without orders
        mock_json_responses = [
            {"errors": "No error, just testing."},
            {"message": "Message from the json response."},
            {"items": []},
        ]
        for expected_response in mock_json_responses:
            with self.assertRaises(SystemExit) as e:
                requests.get = MagicMock(
                    return_value=MockResponse(expected_response, 200)
                )
                OrderEmailResender.fetch_unsent_orders()
                self.assertEqual(e.exception.code, 0)

        # Test API unavailable
        requests.get = Mock(return_value=MockResponse({}, 500))
        requests.get.side_effect = requests.exceptions.ConnectionError()
        with self.assertRaises(requests.exceptions.ConnectionError):
            OrderEmailResender.fetch_unsent_orders()
        requests.get.assert_called()


if __name__ == "__main__":
    unittest.main()
