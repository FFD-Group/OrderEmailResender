from dotenv import load_dotenv
import pendulum
import os
import sys
import requests

load_dotenv()

MAX_EMAIL_ATTEMPTS = os.getenv("MAX_EMAIL_ATTEMPTS")

# WEB VARIABLES
ORG_ID = os.getenv("ORG_ID")
WEB_DOMAIN = os.getenv("WEB_DOMAIN")
WEB_ORDER_EP = WEB_DOMAIN + os.getenv("WEB_ORDER_API_ENDPOINT")
WEB_ORDER_FIELDS = "items[entity_id,increment_id,email_sent,status,status_histories[comment]],errors,message,code,trace,parameters,total_count"
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

# Fetch the Time API at https://timeapi.io/api/timezone/zone?timeZone=Europe%2FLondon
#       The JSON response object should have a 'isDayLightSavingActive' property.
headers = {"accept": "application/json"}
time_response = requests.get(
    "https://timeapi.io/api/timezone/zone?timeZone=Europe%2FLondon"
)
active_DST = True if time_response.json()["isDayLightSavingActive"] else False
if active_DST:
    # Subtract another hour because of Magento API bug which doesn't account for BST.
    # Turn ON when clocks go forward and OFF when clocks go backward.
    SYNC_PERIOD_TIME_STR = SYNC_PERIOD_TIME.subtract(
        hours=1
    ).to_datetime_string()

# WEB ORDER COLLECTION REQUEST
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

# ITERATE ORDERS
for order in json_response["items"]:
    pass
