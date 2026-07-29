import datetime
from zoneinfo import ZoneInfo
from dateutil import parser as date_parser
# We're not working all night, are we? OK, let's define that
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 20
# Also, we need to eat and reset, dude!
LUNCH_START_HOUR = 13  # 1 PM
LUNCH_END_HOUR = 14.5  # 2:30 PM


# print(date_parser.parse("July 21", dayfirst=True))
# print(date_parser.parse("21 de julio", dayfirst=True))

date_obj = datetime.datetime.now(ZoneInfo("America/Mexico_City"))
current = date_obj.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
day_end = date_obj.replace(hours=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)


print(f"current :{current}")
print(f"day_end :{day_end}")