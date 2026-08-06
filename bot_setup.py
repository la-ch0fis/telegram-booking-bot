from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters
)
from calendar_utils import (get_calendar_service, parse_user_datetime, 
    check_availability, create_booking_event, find_user_bookings, format_spanish_dates,
    find_available_slots, get_mexico_holiday, get_user_last_booking, BUSINESS_START_HOUR, 
    BUSINESS_END_HOUR, MIN_DAYS_BETWEEN_BOOKINGS
)
import datetime
import time
from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------------------------------
# TODO: READ THIS, PLEASE!
# NOTE: Flip to False during testing, back to True for real use, DO NOT FORGET!
ENFORCE_WEEKLY_LIMIT = False  
#---------------------------------------------------------------------------------------------------

NAME, DATETIME = range(2)
SESSION_LENGHT_MINUTES = 90
CONFIRM_CANCEL = range(3, 4)[0]

# --- Rate limiting config ---
RATE_LIMIT_MAX_ATTEMPTS = 3
RATE_LIMIT_WINDOW_SECONDS = 3600 # 1 hour

ERROR_MESSAGES = {
    "unclear_time": "Por favor incluye AM/PM (Ejemplo: 'Julio 27, 3pm' o 'Mañana, 3pm').",
    "past_date": "Fecha pasada — por favor escoge una fecha futura.",
    "outside_hours": f"El horario de las sesiones es {BUSINESS_START_HOUR}am y {BUSINESS_END_HOUR - 12}pm. Selecciona una hora dentro de ese rango.",
    "ambigous_date": "Esa fecha no parece válida — por favor verifica el día y mes e intenta de nuevo (Ejemplo: ' Julio 27, 3pm').",
    "sunday": "Disculpa, no agendamos sesiones los domingos. Por favor elige otro día.",
    "holiday": "Es día festivo y no hay sesiones disponibles. Por favor elige otra fecha.",
    "lunch_break": f"Horario reservado para la comida (1:00 PM — 2:30 PM). Por favor elige otro horario.",
    "unparseable": "Disculpa, no entendí — intenta de nuevo, por favor. Ejemplo: 'Julio 27, 3pm'"
}


def check_rate_limit(context, telegram_user_id):
    '''Checks is a user has exceeded allowed booking attempts within the rate-limit window'''
    if "rate_limits" not in context.bot_data:
        context.bot_data["rate_limits"] = {}
    
    now = time.time()
    user_attempts = context.bot_data["rate_limits"].get(telegram_user_id, [])
    user_attempts = [t for t in user_attempts if now - t < RATE_LIMIT_WINDOW_SECONDS]

    if len(user_attempts) >= RATE_LIMIT_MAX_ATTEMPTS:
        context.bot_data["rate_limits"][telegram_user_id] = user_attempts
        return False
    
    user_attempts.append(now)
    context.bot_data["rate_limits"][telegram_user_id] = user_attempts
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("!Hola! ¿Cómo estás? Soy tu asistente virtual Oosouji 🌿\n\n" 
                                    "Puedo ayudarte a agendar tu sesión de Reiki y Bio-magnetismo.\n\n"
                                    "Comandos disponibles:\n"
                                    "/agendar — Reservar una nueva sesión\n"
                                    "/cancelar — Cancelar sesión existente\n"
                                    "¡Escribe /agendar cuando quieras empezar!"
                )
# -------------------------------------------------------------------------------------------------------------------------
# Real reasoning on that weird -MIN_DAYS < days_since < MIN_DAYS check: 
# since last_booking could be a PAST session (already happened, days_since positive) 
# OR a FUTURE one already booked (days_since would be negative, since "now minus a future date" is negative) — 
# this range check catches BOTH cases, Cochise: too-soon-after-a-past-session AND too-close-to-an-already-upcoming-one, in one check.   
# DO NOT FORGET ABOUT THIS

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user_id = update.effective_user.id

    if not check_rate_limit(context, telegram_user_id):
        await update.message.reply_text(
            "Haz alcanzado el límite de intentos por hora.\n"
            "Por favor intenta de nuevo más tarde."
            )
        return ConversationHandler.END
    
    service = get_calendar_service()
    last_booking = get_user_last_booking(service, telegram_user_id)
    print(ENFORCE_WEEKLY_LIMIT)

    if ENFORCE_WEEKLY_LIMIT and last_booking:
        now = datetime.datetime.now(ZoneInfo("America/Mexico_City"))
        days_since = (now - last_booking.astimezone(ZoneInfo("America/Mexico_City"))).days
        print(f'days_since: {days_since}')
        print(f'MIN_DAYS_BETWEEN_BOOKINGS: {MIN_DAYS_BETWEEN_BOOKINGS}')
        print(f'now: {now}')
        print(f'last_booking: {last_booking}')
        if -MIN_DAYS_BETWEEN_BOOKINGS < days_since < MIN_DAYS_BETWEEN_BOOKINGS:
            await update.message.reply_text(
                f"Por motivos de eficiencia del tratamiento, se recomienda esperar al menos "
                f"{MIN_DAYS_BETWEEN_BOOKINGS} días entre sesiones. Por favor intenta agendar más adelante.\n"
                f"En caso de urgencia por favor contáctame directamente."
            )
            return ConversationHandler.END
    await update.message.reply_text("¡Vamos a agendar tu sesión! ¿Cómo te llamas?")
    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # context.user_data["name"] = update.message.text.strip()
    name = update.message.text.strip()
    if len(name) < 3 or len(name) > 60:
        await update.message.reply_text("Por favor introduce un nombre válido.")
        return NAME
    
    context.user_data["name"] = name
    await update.message.reply_text("Perfecto! ¿Cuándo te gustaría reservar? (Ejemplo: 'Julio 21, 4 pm' o '21/07/2026 4pm').\n\n"
                                    "Incluso puedes usar las palabras 'hoy', 'mañana' o 'pasado mañana' (Ejemplo de uso: 'hoy, 4pm' o bien 'mañana, 10am' o 'pasado mañana, 4pm').\n\n"
                                    "Es MUY IMPORTANTE que uses el formato correcto como viene en los ejemplos para poder reservar, por favor.") 
    return DATETIME



async def get_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    holidays_list = context.bot_data["holidays"]
    parsed_iso, error_reason = parse_user_datetime(update.message.text, holidays_list)

    if parsed_iso is None:
        message = ERROR_MESSAGES.get(error_reason, 'Por favor intenta con otra fecha/hora.')
        await update.message.reply_text(message)
        return DATETIME # stay on same state, ask again
    
    start_dt = datetime.datetime.fromisoformat(parsed_iso)
    end_dt = start_dt + datetime.timedelta(minutes=SESSION_LENGHT_MINUTES)

    try:
        service = get_calendar_service()
        is_available = check_availability(service, start_dt.isoformat(), end_dt.isoformat())
    except Exception as e:
        print(f"Calendar error: {e}") # logs real error
        await update.message.reply_text("Una disculpa enorme, tengo problemas para revisar el calendario en este momento, por favor intenta más tarde.")
        return DATETIME
    
    if not is_available:
        #await update.message.reply_text("Ese horario ya esta ocupado. ¿Podrías interntar con otra fecha/hora?")
        available_slots = find_available_slots(service, start_dt, SESSION_LENGHT_MINUTES, holidays_list)
        if not available_slots:
            await update.message.reply_text("Ese horario ya está ocupado y no hay más espacios disponibles ese día. "
                                            "¿Podrías intentar con otra fecha?"
                                )
        else:
            suggestions = " ".join([slot.strftime("%I:%M %p") for slot in available_slots[:3]]) # vailable_slots[:3] <-- Only shoes the first 3 suggestions to avoid screen flooding
            await update.message.reply_text(
                f"Ese horario ya está ocupado. Horarios disponibles ese día: {suggestions}. "
                f"Por favor escribe la fecha con el horario que prefieras, por ejemplo: "
                f"'Julio 30, 9am' o 'Julio 30, 9:30am'. "
            )
        return DATETIME # ask again, stay on same state
    
    name = context.user_data["name"]

    try:
        telegram_user_id = update.effective_user.id
        create_booking_event(service, name, start_dt, end_dt, telegram_user_id)
    except Exception as e:
        print(f"Event creation error: {e}")
        await update.message.reply_text("Revisé la disponibilidad pero no pude finalizar la reservación. Intenta de nuevo.")
        return DATETIME

    await update.message.reply_text(
        f"¡Reservación confirmada {name}!, {format_spanish_dates(start_dt)}. ¡Nos vemos entonces!"
    )
    return ConversationHandler.END


async def cancel_booking_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user_id = update.effective_user.id
    service = get_calendar_service()

    try:
        bookings = find_user_bookings(service, telegram_user_id)
    except Exception as e:
        print(f"Lookup error {e}")
        await update.message.reply_text("Estoy teniendo problemas para revisar la agenda, por favor intenta de nuevo.")
        return ConversationHandler.END    
    
    if not bookings[0]:
        await update.message.reply_text("No tienes ninguna sesión agendada para cancelar.")
        return ConversationHandler.END
    # For now, handle the FIRST upcoming booking first (simplest case)
    booking = bookings[0]
    context.user_data["booking_to_cancel"] = booking["id"]
    start_raw = booking["start"].get("dateTime")
    start_dt = datetime.datetime.fromisoformat(start_raw).astimezone(ZoneInfo("America/Mexico_City"))

    await update.message.reply_text(
        f"Tienes sesión para {format_spanish_dates(start_dt)}."
        f"Escribe SI para cancelar, o NO para conservar tu sesión."
    )
    return CONFIRM_CANCEL


async def confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.strip().lower()
    if answer == "si" or answer == "sí":
        service = get_calendar_service()
        event_id = context.user_data["booking_to_cancel"]

        event = service.events().get(calendarId='primary', eventId=event_id).execute()
        start_raw = event['start'].get('dateTime')
        start_dt = datetime.datetime.fromisoformat(start_raw)
        now = datetime.datetime.now(ZoneInfo("America/Mexico_City"))

        if start_dt < now:
            await update.message.reply_text("Esa sesión ya pasó, no se puede cancelar.")
            return ConversationHandler.END
        
        try:
            service.events().delete(calendarId='primary', eventId=event_id).execute()
            await update.message.reply_text("Tu sesión ha sido cancelada con éxito, saludos.")
        except Exception as e:
            print(f"Concellation error: {e}")
            await update.message.reply_text("Una disculpa, tengo problemas para cancelar tu sesión, intentalo de nuevo o contactame directamente.")
    else:
        await update.message.reply_text("Muy bien, tu sesión sigue activa.")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sesión cancelada.")
    return ConversationHandler.END


async def timeout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("La reservación se canceló por inactividad. Escribe /agendar para intentar de nuevo.")
    return ConversationHandler.END

# Handler for random messages ===============================================================================================
async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Solo puedo ayudarte a agendar sesiones. Escribe /agendar para reservar una cita."
        )

# uknown mistyped commands - silent, no feedback
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("No reconozco ese comando. Prueba con /agendar o /cancelar.")


async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    '''Checks for bookings starting soon and sends a reminder message to the client.
    '''
    service = get_calendar_service()
    now = datetime.datetime.now(ZoneInfo("America/Mexico_City"))
    reminder_window_start = now + datetime.timedelta(hours=23)
    reminder_window_end = now + datetime.timedelta(hours=25)

    event_result = service.events().list(
        calendarId='primary',
        timeMin=reminder_window_start.isoformat(),
        timeMax=reminder_window_end.isoformat(),
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = event_result.get('items', [])

    for event in events:
        telegram_user_id = event.get('extendedProperties', {}).get('private', {}).get('telegram_user_id')
        if telegram_user_id:
            start_raw = event['start']['dateTime']
            start_dt = datetime.datetime.fromisoformat(start_raw).astimezone(ZoneInfo("America/Mexico_City"))
            await context.bot.send_message(
                chat_id=int(telegram_user_id),
                text=f"¡Recordatorio! Tienes una sesión mañana, {format_spanish_dates(start_dt)}. ¡Nos vemos pronto!"
            )


# ====================================================================BUILD===================================================================== #
def build_application(token):
    '''Build and configures the Telegram Aplication with all handlers registered.
       Shared by both the local polling version and the Lambda wenhook version.

       CommandHandler reacts to ONE single message like /start or /book and responds ONCE - it has no memory of "what step are you on"
       So, we need something more suitable for this so we'd use "ConversationHandler" which solves this by tracking STATE - it remembers
       "this user is currently on step 2 (waiting for date), not step 1 (waiting for name)" between messages.
        
       entry_points=[CommandHandler("book", book_start)] — this is what TRIGGERS the conversation (someone sends /book)
       fallbacks=[CommandHandler("cancel", cancel)] — lets the user bail out mid-conversation with /cancel
       filters.TEXT & ~filters.COMMAND — means "accept plain text replies, but NOT if they type another command" — 
       keeps the flow from getting confused if someone types /start mid-booking
    '''
    app = Application.builder().token(token).build()

    service = get_calendar_service()
    print(f"Service: {service}")
    current_year = datetime.datetime.now(ZoneInfo('America/Mexico_City')).year
    # --------------------------------------------------------
    holidays_list = get_mexico_holiday(service, current_year)
    app.bot_data["holidays"] = holidays_list
    # Here's the real architecture, my perro, so you/we won't forget, pay attention: 
    # calendar_utils.py functions like "is_within_business_hours()" and "find_available_slots()" require "holidays_list" as an EXPLICIT parameter every 
    # single time they're called — they don't reach out and grab it from context.bot_data themselves, because calendar_utils.py is supposed to stay 100% platform-agnostic 
    # (no Telegram-specific stuff like context.bot_data allowed in there, remember that design decision from way back).
    # So the ACTUAL flow, my perro: bot_setup.py fetches the holidays ONCE at startup, stores them in app.bot_data["holidays"]. 
    # Then, EVERY time a function in bot_setup.py needs to call something from calendar_utils.py that needs holidays, 
    # it has to manually GRAB the list out of context.bot_data["holidays"] and PASS it in as an argument.
    # --------------------------------------------------------

    app.job_queue.run_repeating(send_reminders, interval=3600, first=10)

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CommandHandler("empezar", start))

    booking_handler = ConversationHandler(
        entry_points = [CommandHandler("agendar", book_start)],
        states = {
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_datetime)],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, timeout_handler)]
        },
        fallbacks = [CommandHandler("cancelar", cancel)],
        conversation_timeout = 90 # seconds of innactivity before auto-canceling
    )
    app.add_handler(booking_handler)

    cancel_handler = ConversationHandler(
        entry_points = [CommandHandler("cancelar", cancel_booking_start)],
        states = {
            CONFIRM_CANCEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_cancel)]
        },
        fallbacks = [CommandHandler("cancelar", cancel)]
    )
    app.add_handler(cancel_handler)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    return app

