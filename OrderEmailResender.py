from dotenv import load_dotenv
import pendulum
import os
import sys
import requests

load_dotenv()

MAX_EMAIL_ATTEMPTS = os.getenv("MAX_EMAIL_ATTEMPTS")

# WEB VARIABLES
WEB_DOMAIN = os.getenv("WEB_DOMAIN")
WEB_HEADERS = {
    "Authorization": os.getenv("WEB_AUTH_HEADER_VALUE"),
    os.getenv("WEB_SECRET_NAME"): os.getenv("WEB_SECRET_PASS"),
}

# TIMINGS & TIMES
TIMEZONE = pendulum.timezone("Europe/London")
time_now = pendulum.now(tz=TIMEZONE)
ORDER_AGE_MINS = os.getenv("ORDER_AGE_MINS")
SYNC_PERIOD_TIME = time_now.subtract(minutes=int(ORDER_AGE_MINS))
SYNC_PERIOD_TIME_STR = SYNC_PERIOD_TIME.to_datetime_string()


def check_daylight_savings_time():
    """Fetch the Time API to determine whether daylight savings is in effect.
    This is required because of a Magento API bug which doesn't account for BST
    and so we need to manually compensate when clocks go forward."""
    global SYNC_PERIOD_TIME_STR
    headers = {"accept": "application/json"}
    time_response = requests.get(
        "https://timeapi.io/api/timezone/zone?timeZone=Europe%2FLondon",
        headers=headers,
    )
    # The JSON response object should have a 'isDayLightSavingActive' property.
    active_DST = (
        True if time_response.json()["isDayLightSavingActive"] else False
    )
    if active_DST:
        SYNC_PERIOD_TIME_STR = SYNC_PERIOD_TIME.subtract(
            hours=1
        ).to_datetime_string()


def fetch_unsent_orders():
    """Build and send a request to Magento to fetch unsent orders."""
    global SYNC_PERIOD_TIME_STR, WEB_HEADERS, WEB_DOMAIN
    WEB_ORDER_FIELDS = (
        "items["
        + "entity_id,increment_id,email_sent,status,status_histories[comment]"
        + "]"
        + ",errors,message,code,trace,parameters,total_count"
    )
    WEB_ORDER_EP = WEB_DOMAIN + os.getenv("WEB_ORDER_API_ENDPOINT")
    # Two 'filter_groups' which combine to form an AND relationship in the criteria.
    order_criteria_parameters = {
        "searchCriteria[filter_groups][0][filters][0][field]": "created_at",
        "searchCriteria[filter_groups][0][filters][0][value]": SYNC_PERIOD_TIME_STR,
        "searchCriteria[filter_groups][0][filters][0][condition_type]": "gteq",
        "searchCriteria[filter_groups][1][filters][0][field]": "email_sent",
        "searchCriteria[filter_groups][1][filters][0][value]": 0,
        "searchCriteria[filter_groups][1][filters][0][condition_type]": "eq",
        "fields": WEB_ORDER_FIELDS,
    }
    raw_order_response = requests.get(
        WEB_ORDER_EP, headers=WEB_HEADERS, params=order_criteria_parameters
    )

    json_response = raw_order_response.json()
    if "total_count" not in json_response:
        if "errors" in json_response and (len(json_response["errors"]) > 0):
            print("Errors", json_response["errors"])

        elif "message" in json_response:
            print("Message", json_response["message"])
        elif "items" in json_response and json_response["items"]:
            print("No orders found since", SYNC_PERIOD_TIME_STR)
        else:
            print(
                "Something happened where the response didn't contain 'total_count' but 'items' wasn't NULL."
            )
        print("Exiting")
        sys.exit(0)
    elif json_response["total_count"] == 0:
        print("No orders found since", SYNC_PERIOD_TIME_STR)
        print("Exiting")
        sys.exit(0)
    else:
        print(
            "Found",
            json_response["total_count"],
            "orders since",
            SYNC_PERIOD_TIME_STR,
        )
        print(json_response["items"])


def process_orders(orders: list) -> None:
    """Process each unsent order by either attempting a recorded resend or
    manually sending the details to sales and alerting admin. Either way, log
    the outcome."""
    global MAX_EMAIL_ATTEMPTS
    for order in orders:
        attempts = _check_resend_attempts(order)
        order_outcome = f"Order {order.increment_id} "
        if attempts >= MAX_EMAIL_ATTEMPTS:
            _alert_admin(order)
            _email_order_to_sales(order)
            order_outcome += "exceeded resend attempts in Magento and has been manually sent to sales."
        else:
            _resend_order_with_magento(order)
            order_outcome = f"has been sent for a resend attempt. This is attemp number {attempts + 1}"
        log_order_outcome(order_outcome)


def _check_resend_attempts(order) -> int:
    """Check the order's comments to parse how many attempts have been made
    to resend the order email already."""
    pass


def _alert_admin(order) -> None:
    """Alert the admin that an order has reached the maximum number of resend
    retries and will be manually sent to the sales inbox."""
    pass


def _email_order_to_sales(order) -> None:
    """Email the order details to the sales inbox manually."""
    pass


def _resend_order_with_magento(order) -> None:
    """Using the Magento API, request for the order email to be resent."""
    pass


def log_order_outcome(details) -> None:
    """Log the outcome of processing an order."""
    pass


if __name__ == "__main__":
    check_daylight_savings_time()
    unsent_orders = fetch_unsent_orders()
    process_orders(unsent_orders)
