from datetime import datetime
from faker import Faker
import OrderEmailResender
import os
import random
import requests
import unittest
from unittest.mock import MagicMock, Mock

fake = Faker("en_GB")


class MockResponse:
    def __init__(self, json_data, status_code):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if 400 <= self.status_code < 500:
            http_error_msg = f"{self.status_code} Client Error"

        elif 500 <= self.status_code < 600:
            http_error_msg = f"{self.status_code} Server Error"

        if http_error_msg:
            raise requests.HTTPError(http_error_msg, response=self)


class TestOrderEmailResender(unittest.TestCase):
    def test_check_daylight_savings_time(self):
        """Test checking daylight savings time and how the function
        handles API availability or response changes.

        Assumptions are made;
        1. The ORDER_AGE_MINS value is set to a double digit value.
            I.E. not 1440 (1 day)
        2. This test will be run during business hours where checking for overlap
            of days won't be necessary.
        """
        DT_FORMAT = "%Y-%m-%d %H:%M:%S"
        ORDER_AGE_MINS = int(os.getenv("ORDER_AGE_MINS"))
        # Test API returns expected data
        requests.get = MagicMock(
            return_value=MockResponse({"isDayLightSavingActive": True}, 200)
        )
        OrderEmailResender.check_daylight_savings_time()
        sync_period_day = datetime.strptime(
            OrderEmailResender.SYNC_PERIOD_TIME_STR, DT_FORMAT
        ).date()
        self.assertEqual(sync_period_day, datetime.today().date())
        requests.get.assert_called()

        # Test API returns unexpected data
        requests.get = MagicMock(return_value=MockResponse({"foo": "bar"}, 200))
        OrderEmailResender.check_daylight_savings_time()
        sync_period_day = datetime.strptime(
            OrderEmailResender.SYNC_PERIOD_TIME_STR, DT_FORMAT
        ).date()
        self.assertEqual(
            sync_period_day,
            datetime.today().date(),
        )
        requests.get.assert_called()

        # Test API is unavailable
        requests.get = Mock(return_value=MockResponse({}, 500))
        requests.get.side_effect = requests.exceptions.ConnectionError()
        with self.assertRaises(requests.exceptions.ConnectionError):
            OrderEmailResender.check_daylight_savings_time()
        sync_period_day = datetime.strptime(
            OrderEmailResender.SYNC_PERIOD_TIME_STR, DT_FORMAT
        ).date()
        self.assertEqual(
            sync_period_day,
            datetime.today().date(),
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

    def test_check_resend_attempts(self):
        """Test checking how many attempts to resend have been made
        on an order by parsing the order's comment history for
        comments starting with the prefix."""
        PREFIX = OrderEmailResender.COMMENT_PREFIX

        # Test normal expected operation
        test_order_obj = {
            "email_sent": 0,
            "entity_id": random.randint(10_000, 99_999),
            "increment_id": "60000" + str(random.randint(10_000, 99_999)),
            "status": random.choice(
                ["processing", "new", "pending_payment", "complete"]
            ),
            "status_histories": [
                {"comment": PREFIX + " Attempt #1"},
                {"comment": PREFIX + " Attempt #2"},
            ],
        }
        attempts = OrderEmailResender._check_resend_attempts(test_order_obj)
        self.assertEqual(attempts, 2)

        # Test no comments on order
        test_order_obj["status_histories"] = []
        attempts = OrderEmailResender._check_resend_attempts(test_order_obj)
        self.assertEqual(attempts, 0)

        # Test missing "status_histories" on order object
        del test_order_obj["status_histories"]
        attempts = OrderEmailResender._check_resend_attempts(test_order_obj)
        self.assertEqual(attempts, 0)

        # Test more comments than expected on order object
        test_order_obj["status_histories"] = []
        for i in range(4, random.randint(5, 50)):
            test_order_obj["status_histories"].append(
                {"comment": PREFIX + f" Attempt #{i}"}
            )
        attempts = OrderEmailResender._check_resend_attempts(test_order_obj)
        self.assertEqual(attempts, len(test_order_obj["status_histories"]))

    def test_alert_admin(self):
        """Test sending an alert to admin."""
        PREFIX = OrderEmailResender.COMMENT_PREFIX
        ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL")

        test_order_obj = {
            "email_sent": 0,
            "entity_id": random.randint(10_000, 99_999),
            "increment_id": "60000" + str(random.randint(10_000, 99_999)),
            "status": random.choice(
                ["processing", "new", "pending_payment", "complete"]
            ),
            "status_histories": [
                {"comment": PREFIX + " Attempt #1"},
                {"comment": PREFIX + " Attempt #2"},
                {"comment": PREFIX + " Attempt #3"},
            ],
        }

        # Test successful alert sent
        requests.post = Mock(
            return_value=MockResponse({"message": "success"}, 200)
        )
        OrderEmailResender._alert_admin(test_order_obj)
        order_entity_id = test_order_obj["entity_id"]
        order_increment_id = test_order_obj["increment_id"]
        requests.post.assert_called_once_with(
            ALERT_WEBHOOK_URL,
            json={
                "entity_id": order_entity_id,
                "increment_id": order_increment_id,
                "message": f"Order {order_increment_id} ({order_entity_id})"
                + " could not be sent by Magento and has been manually sent to sales.",
            },
        )

        # Test alert webhook unavailable
        requests.post = Mock(return_value=MockResponse({}, 500))
        OrderEmailResender._alert_admin(test_order_obj)
        requests.post.assert_called_once_with(
            ALERT_WEBHOOK_URL,
            json={
                "entity_id": order_entity_id,
                "increment_id": order_increment_id,
                "message": f"Order {order_increment_id} ({order_entity_id})"
                + " could not be sent by Magento and has been manually sent to sales.",
            },
        )

    def test_email_order_to_sales(self):
        """Test sending the order details to a service which
        will email the sales team."""
        PREFIX = OrderEmailResender.COMMENT_PREFIX
        EMAIL_WEBHOOK_URL = os.getenv("EMAIL_WEBHOOK_URL")
        WEB_ORDER_API_ENDPOINT = os.getenv("WEB_DOMAIN") + os.getenv(
            "WEB_ORDER_API_ENDPOINT"
        )

        test_order_obj = {
            "email_sent": 0,
            "entity_id": random.randint(10_000, 99_999),
            "increment_id": "60000" + str(random.randint(10_000, 99_999)),
            "status": random.choice(
                ["processing", "new", "pending_payment", "complete"]
            ),
            "status_histories": [
                {"comment": PREFIX + " Attempt #1"},
                {"comment": PREFIX + " Attempt #2"},
                {"comment": PREFIX + " Attempt #3"},
            ],
        }
        order_increment_id = test_order_obj["increment_id"]
        order_entity_id = str(test_order_obj["entity_id"])

        # Test successful API call for order details + successful webhook sent
        order_company_name = fake.company()
        mock_api_order = {
            "customer_name": order_company_name,
            "increment_id": order_increment_id,
            "items": [
                {
                    "name": "A fake item",
                    "sku": fake.first_name(),
                    "qty_ordered": random.randint(1, 99),
                    "row_total": random.uniform(0.01, 99.99),
                }
            ],
            "billing_address": {
                "city": fake.city(),
                "company": order_company_name,
                "email": fake.email(),
                "firstname": fake.first_name(),
                "lastname": fake.last_name(),
                "postcode": fake.postcode(),
                "region": fake.city(),
                "street": [
                    fake.street_address(),
                    fake.street_name(),
                ],
                "telephone": fake.phone_number(),
            },
            "payment": {
                "method": random.choice(["BACS", "Card", "Cash", "Cheque"]),
            },
            "subtotal": random.uniform(0.01, 99_999),
            "grand_total": random.uniform(0.01, 99_999),
            "extension_attributes": {
                "shipping_assignments": [
                    {
                        "shipping": {
                            "address": {
                                "city": fake.city(),
                                "company": order_company_name,
                                "email": fake.email(),
                                "firstname": fake.first_name(),
                                "lastname": fake.last_name(),
                                "postcode": fake.postcode(),
                                "region": fake.city(),
                                "street": [
                                    fake.street_address(),
                                    fake.street_name(),
                                ],
                                "telephone": fake.phone_number(),
                            },
                            "method": "Standard shipping",
                            "total": {
                                "shipping_amount": random.uniform(0, 99.99),
                                "shipping_incl_tax": random.uniform(0, 99.99),
                            },
                        },
                    }
                ],
            },
            os.getenv(
                "WEB_ORDER_COMMENT_FIELD"
            ): "Please knock on the red door rather than the blue.",
        }
        requests.get = Mock(
            return_value=MockResponse(
                mock_api_order,
                200,
            )
        )
        requests.post = Mock(
            return_value=MockResponse({"message": "success"}, 200)
        )

        OrderEmailResender._email_order_to_sales(test_order_obj)

        requests.get.assert_called_once_with(
            WEB_ORDER_API_ENDPOINT + order_entity_id
        )
        requests.post.assert_called_once_with(
            EMAIL_WEBHOOK_URL,
            json={
                "customer_name": order_company_name,
                "increment_id": order_increment_id,
                "billing_address": mock_api_order["billing_address"],
                "shipping_address": mock_api_order["extension_attributes"][
                    "shipping_assignments"
                ][0]["shipping"]["address"],
                "payment_method": mock_api_order["payment"]["method"],
                "shipping_method": mock_api_order["extension_attributes"][
                    "shipping_assignments"
                ][0]["shipping"]["method"],
                "items": mock_api_order["items"],
                "shipping_cost": mock_api_order["extension_attributes"][
                    "shipping_assignments"
                ][0]["shipping"]["total"],
                "subtotal": mock_api_order["subtotal"],
                "grand_total": mock_api_order["grand_total"],
                "order_comment": mock_api_order[
                    os.getenv("WEB_ORDER_COMMENT_FIELD")
                ],
            },
        )

        # Test Unsuccessful API call for order details
        requests.get = Mock(
            return_value=MockResponse(
                {
                    "message": "Example error.",
                    "errors": [
                        {
                            "message": "Order not found.",
                            "parameters": [
                                {
                                    "resources": "Magento_Sales::view_order",
                                    "fieldName": "{id}",
                                    "fieldValue": "1234",
                                }
                            ],
                        }
                    ],
                    "code": "0",
                    "parameters": [
                        {
                            "resources": "Magento_Sales::view_order",
                            "fieldName": "{id}",
                            "fieldValue": "1234",
                        }
                    ],
                    "trace": "No entity for the given id at line 10 of some file.",
                },
                401,
            )
        )
        with self.assertRaises(requests.HTTPError):
            OrderEmailResender._email_order_to_sales(test_order_obj)

        requests.get.assert_called_once_with(
            WEB_ORDER_API_ENDPOINT + order_entity_id
        )

        # Test successful API call for order details + webhook unavailable
        requests.get = Mock(return_value=MockResponse(mock_api_order, 200))
        requests.post = Mock(return_value=MockResponse({}, 500))
        with self.assertRaises(requests.HTTPError):
            OrderEmailResender._email_order_to_sales(test_order_obj)
        requests.get.assert_called_once_with(
            WEB_ORDER_API_ENDPOINT + order_entity_id
        )
        requests.post.assert_called_once_with(
            EMAIL_WEBHOOK_URL,
            json={
                "customer_name": order_company_name,
                "increment_id": order_increment_id,
                "billing_address": mock_api_order["billing_address"],
                "shipping_address": mock_api_order["extension_attributes"][
                    "shipping_assignments"
                ][0]["shipping"]["address"],
                "payment_method": mock_api_order["payment"]["method"],
                "shipping_method": mock_api_order["extension_attributes"][
                    "shipping_assignments"
                ][0]["shipping"]["method"],
                "items": mock_api_order["items"],
                "shipping_cost": mock_api_order["extension_attributes"][
                    "shipping_assignments"
                ][0]["shipping"]["total"],
                "subtotal": mock_api_order["subtotal"],
                "grand_total": mock_api_order["grand_total"],
                "order_comment": mock_api_order[
                    os.getenv("WEB_ORDER_COMMENT_FIELD")
                ],
            },
        )

    def test_resend_order_with_magento(self):
        """Test sending a request to the Magento API to have an order email
        resent."""
        order_entity_id = random.randint(1_000, 9_999)
        WEB_ORDER_EMAIL_API_ENDPOINT = (
            os.getenv("WEB_DOMAIN")
            + os.getenv("WEB_ORDER_API_ENDPOINT")
            + str(order_entity_id)
            + "/emails"
        )
        order_arg = {"entity_id": order_entity_id}

        # Test successfull API call
        requests.post = Mock(return_value=MockResponse("true", 200))
        result = OrderEmailResender._resend_order_with_magento(order_arg)
        requests.post.assert_called_once_with(WEB_ORDER_EMAIL_API_ENDPOINT)
        self.assertEqual(result, True)

        # Test successful API call but email not sent
        requests.post = Mock(return_value=MockResponse("false", 200))
        result = OrderEmailResender._resend_order_with_magento(order_arg)
        requests.post.assert_called_once_with(WEB_ORDER_EMAIL_API_ENDPOINT)
        self.assertEqual(result, False)

        # Test unsuccessfull API call
        requests.post = Mock(return_value=MockResponse({}, 500))
        with self.assertRaises(requests.HTTPError):
            result = OrderEmailResender._resend_order_with_magento(order_arg)
        requests.post.assert_called_once_with(WEB_ORDER_EMAIL_API_ENDPOINT)
        self.assertEqual(result, False)


if __name__ == "__main__":
    unittest.main()
