from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import datetime
from zoneinfo import ZoneInfo
from dateutil import parser as date_parser


# SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


SCOPES = ['https://www.googleapis.com/auth/calendar']

# We will use this for later development, in case we are international but let's keep it so I won't forget
SPANISH_MONTHS = {
    "enero": "january", "febrero": "february", "marzo": "march",
    "abril": "april", "mayo": "may", "junio": "june",
    "julio": "july", "agosto": "august", "septiembre": "september",
    "octubre": "october", "noviembre": "november", "diciembre": "december"
}


# Spanish month for México only
SPANISH_MONTHS_DISPLAY = {
    1 :"enero", 2: "febrero", 3: "marzo",
    4: "abril", 5: "mayo", 6: "junio", 
    7: "julio", 8: "agosto", 9: "septiembre",
    10: "octubre", 11: "noviembre", 12: "diciembre"
}


RELATIVE_DATES = {
    "hoy": 0,
    "today": 0,
    "mañana": 1,
    "tomorrow": 1,
    "pasado mañana": 2,
    "day after tomorrow": 2
}

# We're not working all night, are we? OK, let's define that
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 20
# Also, we need to eat and reset, dude!
LUNCH_START_HOUR = 13  # 1 PM
LUNCH_END_HOUR = 14.5  # 2:30 PM

# Holidays, 
# TODO: we need to do this automatic instead of updating these days each year
HOLIDAYS_2026 = [
    "2026-01-01",  # New year
    "2026-02-02",  # Constitution day
    "2026-03-16",  # Benito Juárez (observed)
    "2026-05-01",  # Labor day
    "2026-09-16",  # Idependence day
    "2026-11-16",  # Revolution day
    "2026-12-25",  # Christmas
]


def get_calendar_service():
    '''Authenticates with Google Calendar via OAuth and returns a usable service object.
       Loads a saved token if available; otherwise opens a browser for the user to log in
       and approve access, then saves the resulting token for future runs.
    '''
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)



def resolve_relative_date(text):
    '''It scans the user's text for relative-date words like 'mañana', 
       checking longest phrases first to avoid partial-match mistakes, 
       calculates the ACTUAL date those words represent, and swaps the word 
       for a real date string before dateutil ever tries to parse it.
    '''
    text_lower = text.lower()
    for phrase, days_offset in sorted(RELATIVE_DATES.items(), key=lambda x: -len(x[0])):
        # print(phrase, days_offset)
        if phrase in text_lower:
            target_date = (datetime.datetime.now(ZoneInfo("America/Mexico_City")) + datetime.timedelta(days=days_offset)).strftime("%Y-%m-%d")
            text_lower = text_lower.replace(phrase, target_date)
            return text_lower
    return text_lower



def translate_spanish_month(text):
    '''Replaces Spanish month names (e.g. 'julio') with their English equivalents
       (e.g. 'july') so dateutil.parser can correctly interpret the text.
    '''
    text_lower = text.lower()
    for es, en in SPANISH_MONTHS.items():
        text_lower = text_lower.replace(es, en)
    return text_lower



def parse_user_datetime(raw_text):
    '''Converts casual, free-text user input (mixed Spanish/English, relative dates,
       various date formats) into a proper ISO 8601 datetime string usable by the
       Google Calendar API.
       Stricts: Rejects any input containing unrecognized text, not just valid date/time.
       Returns a tuple: (parsed_iso_or_None, error_reason_or_None)
       Detects wrong day for a month, like July 32, which is wrong.
    '''
    text = resolve_relative_date(raw_text)
    text = translate_spanish_month(text)
    # text = strip_filler(text)
    print(text)

    # Require an explicit time marker or avoid ambiguous numbers like "3" or "4"
    # has_am_pm / has_colon_time — checks if the input has EITHER "am"/"pm" somewhere, 
    # OR a colon (like "15:00"). If NEITHER is present, we reject it immediately, before even trying to parse — no ambiguous bare numbers slip through
    has_am_pm = 'am' in text.lower() or 'pm' in text.lower()
    has_colon_time = ':' in text
    if not has_am_pm and not has_colon_time:
        return None, "unclear_time"

    try:
        default1 = datetime.datetime(2020, 1, 1, tzinfo=ZoneInfo("America/Mexico_City"))
        default2 = datetime.datetime(2021, 6, 15, tzinfo=ZoneInfo("America/Mexico_City"))

        dt1 = date_parser.parse(text, dayfirst=True, fuzzy=False, default=default1)
        dt2 = date_parser.parse(text, dayfirst=True, fuzzy=False, default=default2)

        if (dt1.day, dt1.month) != (dt2.day, dt2.month):
            return None, "ambigous_date" # the day/month wasn't explicitly given/valid
        
        now_naive = datetime.datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None, minute=0, second=0, microsecond=0)
        dt = date_parser.parse(text, dayfirst=True, fuzzy=False, default=now_naive)
        dt = dt.replace(tzinfo=ZoneInfo("America/Mexico_City"))
        print('dt antes' + str(dt))
        now = datetime.datetime.now(ZoneInfo("America/Mexico_City"))
        print('now ' + str(now))
        print('dt ' + str(dt))

        if dt < now: # NOTE: if dt < now: return None — catches any resolved date/time that's already in the past, like your July 2003 bug
            return None, "past_date"
        
        hours_check = is_within_business_hours(dt)
        if hours_check is not None:
            return None, hours_check
        # if not is_within_business_hours(dt):
        #    return None, "outside_hours"
        
        return dt.isoformat(), None
    
    except (ValueError, OverflowError):
        return None, "unparseable"



def check_availability(service, start_time, end_time):
    '''Checks Google Calendar's freebusy data to determine if the given time window
       is open. Returns True if no conflicting events exist, False if something's booked.
    '''
    body = {
        "timeMin": start_time,
        "timeMax": end_time,
        "timeZone": "America/Chicago",
        "items": [{"id": "primary"}]
    }
    result = service.freebusy().query(body=body).execute()
    busy_times = result['calendars']['primary']['busy']

    return len(busy_times) == 0


def find_available_slots(service, date_obj, session_length_minutes):
    '''Scans a single day for available session slots, respecting business hours,
       lunch break, and session length. Returns a list of available datetime objects.
    '''
    available_slots = []
    current = date_obj.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
    day_end = date_obj.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)

    while current + datetime.timedelta(minutes=session_length_minutes) <= day_end:
        reason = is_within_business_hours(current)
        if reason is None:
            slot_end = current + datetime.timedelta(minutes=session_length_minutes)
            # print('slot_end value: ' + str(slot_end))
            is_free = check_availability(service, current.isoformat(), slot_end.isoformat())
            if is_free:
                available_slots.append(current)
        current += datetime.timedelta(minutes=30) # check every 30-min increment

    return available_slots



def create_booking_event(service, name, start_dt, end_dt, telegram_user_id):
    '''Creates a real Google Calendar event for a confirmed booking, tagging it
       with the Telegram user ID so it can be looked up later for cancellation.
       1. New parameter "telegram_user_id" — we'll grab this from "update.effective_user.id" in the bot (Telegram gives every user a unique numeric ID 
          automatically, no extra setup needed).
       2. extendedProperties.private.telegram_user_id — this is metadata stored ON the event itself, invisible to you when just. 
          looking at the calendar normally, but queryable via code.
       3. Return the event ID (not just the link) — we need this ID later for actually CANCELING (deleting) the specific event.
    '''
    event = {
        'summary': f'Session with {name}',
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'America/Chicago'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'America/Chicago'},
        'extendedProperties': {
            'private': {
                'telegram_user_id': str(telegram_user_id)
            }
        }
    }
    create_event = service.events().insert(calendarId='primary', body=event).execute()
    return create_event.get('id')


def find_user_bookings(service, telegram_user_id):
    '''Searches the calendar for upcoming events taggd with this Telegram user's ID,
       so they can be shown/cancelled.
    '''
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    events_result = service.events().list(
        calendarId = 'primary',
        timeMin = now,
        privateExtendedProperty = f'telegram_user_id={telegram_user_id}',
        singleEvents = True,
        orderBy = 'startTime'
    ).execute()
    return events_result.get('items', [])


def is_holiday(dt):
    '''Check whether the given date falls on a defined Mexican holiday'''
    return dt.strftime("%Y-%m-%d") in HOLIDAYS_2026


def is_within_business_hours(dt):
    '''Checks whether a given date falls within defined business hours.
       Excludes Sundays entirely. 
    '''
    if dt.weekday() == 6:  # Monday=0....Sunday=6
        return "sunday"
    
    if is_holiday(dt):
        return "holiday"
    
    if not (BUSINESS_START_HOUR <= dt.hour < BUSINESS_END_HOUR):
        return "outside_hours"
    
    time_as_decimal = dt.hour + dt.minute / 60
    if LUNCH_START_HOUR <= time_as_decimal < LUNCH_END_HOUR:
        return "lunch_break"
    
    return None
# Real technical note, cuz — a small but meaningful difference: 
# SQL's BETWEEN 9 AND 20 is normally INCLUSIVE on both ends (9 counts, AND 20 counts). 
# Python's chained comparison here is inclusive on the LEFT (<=), but EXCLUSIVE on the RIGHT (<) — 
# meaning dt.hour can be exactly 9, but NOT exactly 20. That's actually intentional here, cuz — 
# we want the business day to run FROM 9am UP TO (but not including) 8pm, so a booking exactly AT 8pm wouldn't count as "within hours" 
# (since the session would run past closing).    

def format_spanish_dates(dt):
    '''Formats a datetime into natural, readable Spanish string
       (e.g. "27 de Julio de 2026 a las 3:00 PM")
    '''
    day = dt.day
    month = SPANISH_MONTHS_DISPLAY[dt.month]
    year = dt.year
    time_str = dt.strftime("%I:%M %p").lstrip("0") # removes leading zero. e.g. "3:00 PM" not "03:00 PM"

    return f"{day} de {month} de {year} a las {time_str}"
