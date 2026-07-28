import datetime
from zoneinfo import ZoneInfo
from dateutil import parser as date_parser

print(date_parser.parse("July 21", dayfirst=True))
print(date_parser.parse("21 de julio", dayfirst=True))