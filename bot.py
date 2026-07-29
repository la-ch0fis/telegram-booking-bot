import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters
)
from calendar_utils import (get_calendar_service, parse_user_datetime, 
    check_availability, create_booking_event, find_user_bookings, format_spanish_dates,
    find_available_slots, BUSINESS_START_HOUR, BUSINESS_END_HOUR
)
import datetime
from zoneinfo import ZoneInfo


'''
What this does, plain talk: it's the absolute minimum "hello world" bot — when someone messages your bot with /start, it replies with a greeting. 
No booking logic yet, this is just proving the CONNECTION works before we add complexity.
'''

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NAME, DATETIME = range(2)
SESSION_LENGHT_MINUTES = 90
CONFIRM_CANCEL = range(3, 4)[0]


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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("!Hola! ¿Cómo estás? Soy tu asistente virtual Oosouji 🌿\n\n" 
                                    "Puedo ayudarte a agendar tu sesión de Reiki y Bio-magnetismo.\n\n"
                                    "Comandos disponibles:\n"
                                    "/agendar — Reservar una nueva sesión\n"
                                    "/cancelar — Cancelar sesión existente\n"
                                    "¡Escribe /agendar cuando quieras empezar!"
                )
    

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Vamos a agendar tu sesión! ¿Cómo te llamas?")
    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Perfecto! ¿Cuándo te gustaría reservar? (Ejemplo: 'Julio 21, 4 pm' o '21/07/2026 4pm').\n\n"
                                    "Incluso puedes usar las palabras 'hoy', 'mañana' o 'pasado mañana' (Ejemplo de uso: 'hoy, 4pm' o bien 'mañana, 10am' o 'pasado mañana, 4pm').\n\n"
                                    "Es MUY IMPORTANTE que uses el formato correcto como viene en los ejemplos para poder reservar, por favor.") 
    return DATETIME



async def get_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed_iso, error_reason = parse_user_datetime(update.message.text)

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
        available_slots = find_available_slots(service, start_dt, SESSION_LENGHT_MINUTES)
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



# async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     context.user_data["time"] = update.message.text
#     name = context.user_data["name"]
#     date = context.user_data["date"]
#     time = context.user_data["time"]
#     await update.message.reply_text(f"Booking confirmed: {name}, {date} at {time}. (Not saved anywhere yet - that's next!)")
#     return ConversationHandler.END

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



def main():
    ''' CommandHandler reacts to ONE single message like /start or /book and responds ONCE - it has no memory of "what step are you on"
        So, we need something more suitable for this so we'd use "ConversationHandler" which solves this by tracking STATE - it remembers
        "this user is currently on step 2 (waiting for date), not step 1 (waiting for name)" between messages.
        
        entry_points=[CommandHandler("book", book_start)] — this is what TRIGGERS the conversation (someone sends /book)
        fallbacks=[CommandHandler("cancel", cancel)] — lets the user bail out mid-conversation with /cancel
        filters.TEXT & ~filters.COMMAND — means "accept plain text replies, but NOT if they type another command" — 
        keeps the flow from getting confused if someone types /start mid-booking
    '''
    app = Application.builder().token(TOKEN).build()

    app.job_queue.run_repeating(send_reminders, interval=3600, first=10) # check every hour, starting 10 sec after launch
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("empezar", start))

    booking_handler = ConversationHandler(
        entry_points=[CommandHandler("agendar", book_start)],
        states = {
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_datetime)],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, timeout_handler)]
        },
        fallbacks=[CommandHandler("cancelar", cancel)],
        conversation_timeout=60 # seconds of inactivity before auto-ending
    )
    app.add_handler(booking_handler)

    cancel_handler = ConversationHandler(
        entry_points = [CommandHandler("cancelar", cancel_booking_start)],
        states = {
            CONFIRM_CANCEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_cancel)],
        },
        fallbacks=[CommandHandler("cancelar", cancel)]
    )
    app.add_handler(cancel_handler)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    print("Bot is running...")
    app.run_polling()



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

# ==============================================================================================================================================================
if __name__ == "__main__":
    main()


