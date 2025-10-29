import json
from dotenv import load_dotenv
import logging
import pendulum
import os
import sys
import requests

load_dotenv()

MAX_EMAIL_ATTEMPTS = int(os.getenv("MAX_EMAIL_ATTEMPTS"))
COMMENT_PREFIX = str(os.getenv("COMMENT_PREFIX"))

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

logger = logging.getLogger(__name__)
logging.basicConfig(filename="order_email_resender.log", level=logging.INFO)


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
    response_json = time_response.json()
    # The JSON response object should have a 'isDayLightSavingActive' property.
    if "isDayLightSavingActive" in response_json:
        active_DST = True if response_json["isDayLightSavingActive"] else False
    else:
        # Assume DST as this will cover a larger time period.
        active_DST = True
    if active_DST:
        SYNC_PERIOD_TIME_STR = SYNC_PERIOD_TIME.subtract(
            hours=1
        ).to_datetime_string()


def fetch_unsent_orders() -> list:
    """Build and send a request to Magento to fetch unsent orders."""
    WEB_ORDER_FIELDS = (
        "items["
        + "entity_id,increment_id,email_sent,status,status_histories[comment]"
        + "]"
        + ",errors,message,code,trace,parameters,total_count"
    )
    WEB_ORDER_EP = WEB_DOMAIN + os.getenv("WEB_ORDERS_API_ENDPOINT")
    # Two 'filter_groups' which combine to form an AND relationship in the criteria.
    # Can't filter by 'email_sent => eq 0' field as it doesn't exist on the order entity
    #       until it is set to 1.
    order_criteria_parameters = {
        "searchCriteria[filter_groups][0][filters][0][field]": "created_at",
        "searchCriteria[filter_groups][0][filters][0][value]": SYNC_PERIOD_TIME_STR,
        "searchCriteria[filter_groups][0][filters][0][condition_type]": "gteq",
        "fields": WEB_ORDER_FIELDS,
    }
    raw_order_response = requests.get(
        WEB_ORDER_EP, headers=WEB_HEADERS, params=order_criteria_parameters
    )

    json_response = raw_order_response.json()
    if "total_count" not in json_response:
        if "errors" in json_response and (len(json_response["errors"]) > 0):
            logger.info("Errors" + json.dumps(json_response["errors"]))

        elif "message" in json_response:
            logger.info("Message" + json.dumps(json_response["message"]))
        elif "items" in json_response and json_response["items"]:
            logger.info("No orders found since" + SYNC_PERIOD_TIME_STR)
        else:
            logger.info(
                "Something happened where the response didn't contain 'total_count' but 'items' wasn't NULL."
            )
        logger.info("Exiting")
        sys.exit(0)
    elif json_response["total_count"] == 0:
        logger.info("No orders found since " + SYNC_PERIOD_TIME_STR)
        logger.info("Exiting")
        sys.exit(0)
    else:
        logger.info(
            "Found "
            + str(json_response["total_count"])
            + " orders since "
            + SYNC_PERIOD_TIME_STR
        )
    return list(json_response["items"])


def process_orders(orders: list) -> None:
    """Process each unsent order by either attempting a recorded resend or
    manually sending the details to sales and alerting admin. Either way, log
    the outcome."""
    for order in orders:
        # If 'email_sent' is set - it has been sent already by Magento.
        if "email_sent" in order:
            continue
        attempts = _check_resend_attempts(order)
        order_outcome = f"Order {order['increment_id']} "
        if attempts >= MAX_EMAIL_ATTEMPTS:
            _alert_admin(order)
            _email_order_to_sales(order)
            order_outcome += "exceeded resend attempts in Magento and has been manually sent to sales."
        else:
            sent = _resend_order_with_magento(order)
            if sent:
                order_outcome += f"has been sent for a resend attempt. "
            else:
                order_outcome += f"should have been resent with Magento but something went wrong. "
            order_outcome += f"This is attempt number {attempts + 1}"
        _log_order_outcome(order_outcome)


def _check_resend_attempts(order) -> int:
    """Check the order's comments to parse how many attempts have been made
    to resend the order email already."""
    if "status_histories" not in order:
        return 0
    order_comments = order["status_histories"]
    if len(order_comments) == 0:
        return 0
    attempts = sum(
        1 for n in order_comments if n["comment"].startswith(COMMENT_PREFIX)
    )
    return attempts


def _alert_admin(order) -> None:
    """Alert the admin that an order has reached the maximum number of resend
    retries and will be manually sent to the sales inbox."""
    ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL")
    if "entity_id" not in order:
        raise ValueError("Invalid order object")
    if "increment_id" not in order:
        raise ValueError("Invalid order object")

    order_id = order["entity_id"]
    incr_id = order["increment_id"]
    payload = {
        "entity_id": order_id,
        "increment_id": incr_id,
        "message": f"Order {incr_id} ({order_id})"
        + " could not be sent by Magento and has been manually sent to sales.",
    }
    requests.post(ALERT_WEBHOOK_URL, json=payload)


def _email_order_to_sales(order) -> None:
    """Email the order details to the sales inbox manually."""
    if "entity_id" not in order:
        raise ValueError("No entity ID present on order.")
    WEB_ORDER_API_ENDPOINT = os.getenv("WEB_DOMAIN") + os.getenv(
        "WEB_ORDER_API_ENDPOINT"
    )
    EMAIL_WEBHOOK_URL = os.getenv("EMAIL_WEBHOOK_URL")
    get_order_url = WEB_ORDER_API_ENDPOINT + str(order["entity_id"])
    api_response = requests.get(get_order_url)
    if api_response.status_code != 200:
        raise api_response.raise_for_status()
    full_order = api_response.json()
    # Using the first instance of shipping assignment which
    # works for FFD's business logic.
    order_payload = {
        "customer_name": full_order["customer_name"],
        "increment_id": full_order["increment_id"],
        "billing_address": full_order["billing_address"],
        "shipping_address": full_order["extension_attributes"][
            "shipping_assignments"
        ][0]["shipping"]["address"],
        "payment_method": full_order["payment"]["method"],
        "shipping_method": full_order["extension_attributes"][
            "shipping_assignments"
        ][0]["shipping"]["method"],
        "items": full_order["items"],
        "shipping_cost": full_order["extension_attributes"][
            "shipping_assignments"
        ][0]["shipping"]["total"],
        "subtotal": full_order["subtotal"],
        "grand_total": full_order["grand_total"],
        "order_comment": full_order[os.getenv("WEB_ORDER_COMMENT_FIELD")],
    }
    webhook_response = requests.post(EMAIL_WEBHOOK_URL, json=order_payload)
    if webhook_response.status_code != 200:
        raise webhook_response.raise_for_status()


def _resend_order_with_magento(order) -> bool:
    """Using the Magento API, request for the order email to be resent."""
    if "entity_id" not in order:
        raise ValueError("No entity ID present on order")
    order_entity_id = order["entity_id"]
    WEB_ORDER_EMAIL_API_ENDPOINT = (
        os.getenv("WEB_DOMAIN")
        + os.getenv("WEB_ORDER_API_ENDPOINT")
        + str(order_entity_id)
        + "/emails"
    )
    response = requests.post(WEB_ORDER_EMAIL_API_ENDPOINT, headers=WEB_HEADERS)
    logger.info("Magento resending email: " + str(response))
    if response.status_code != 200:
        response.raise_for_status()
    return response.json() == "true"


def _log_order_outcome(details) -> None:
    """Log the outcome of processing an order."""
    logger.info(details)


if __name__ == "__main__":
    check_daylight_savings_time()
    unsent_orders = fetch_unsent_orders()
    process_orders(unsent_orders)
