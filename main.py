import asyncio
import json
import logging
import multiprocessing
import os
import time

import paho.mqtt.client as mqtt
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

mqttc = None
mqtt_url = os.environ['MQTT_URL']
mqtt_port = int(os.environ['MQTT_PORT'])
bot_token = os.environ['APIKEY']

chat_list = json.loads(os.environ['CHAT_LIST'])

last_message_time = time.time()

call_topic = "door/call"
state_topic = "door/state"
lock_topic = "lock"

lock_state = "0"

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)


async def restrict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"User {update.effective_user.id} from chat {update.effective_chat.id} sends {update.message.text}")


# === TELEGRAM COMMAND HANDLERS === #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received /start command.")
    chat_id = update.message.chat_id
    await context.bot.send_message(chat_id=chat_id,
                                   text="Hi.")


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received /stop command.")
    chat_id = update.message.chat_id
    await context.bot.send_message(chat_id=chat_id, text="Bye.")


async def open_door(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received /open_door command.")
    send_mqtt_message("1")


async def drop_call(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received /drop_call command.")
    send_mqtt_message("2")


async def open_on_next_call_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received /open_on_next_call command.")
    await context.bot.send_message(chat_id=update.effective_chat.id,
                                   text=f"Will open on next call automatically.")


def on_subscribe(client, userdata, mid, reason_code_list, properties):
    if reason_code_list[0].is_failure:
        logging.error(f"Broker rejected you subscription: {reason_code_list[0]}")
    else:
        logging.info(f"Broker granted the following QoS: {reason_code_list[0].value}")


def on_unsubscribe(client, userdata, mid, reason_code_list, properties):
    if len(reason_code_list) == 0 or not reason_code_list[0].is_failure:
        logging.info("unsubscribe succeeded (if SUBACK is received in MQTTv3 it success)")
    else:
        logging.error(f"Broker replied with failure: {reason_code_list[0]}")
    client.disconnect()


def on_message(client, userdata, message):
    logging.info(f"Inconming value {message.payload.decode()} for  {message.topic}")
    global last_message_time
    global lock_state

    try:
        logging.info(f"message: {message.topic}")
        logging.info(f"Last message time: {last_message_time}, current time: {time.time()}")
        if message.topic == call_topic:
            if last_message_time + 20 < time.time():
                last_message_time = time.time()
                logging.info(f"Sending message")
                for chat in chat_list:
                    bot = Bot(token=bot_token)
                    asyncio.run(bot.send_message(chat_id=chat, text="/open\n/drop"))
            else:
                logging.info(f"Ignoring calls in 20 sec starting from: {last_message_time}")
        if message.topic == lock_topic:
            logging.info(f"Door state changed {lock_state}")
            if lock_state != message.payload.decode():
                lock_state = message.payload.decode()
                for chat in chat_list:
                    bot = Bot(token=bot_token)
                    if "1" == lock_state:
                        asyncio.run(bot.send_message(chat_id=chat, text="Lock opened"))
                    else:
                        asyncio.run(bot.send_message(chat_id=chat, text="Lock closed"))

    except IOError:
        mqttc.publish("/error", payload="Request failed")
        logging.exception(f"Request failed")


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        logging.error(f"Failed to connect: {reason_code}. loop_forever() will retry connection")
    else:
        client.subscribe(call_topic)
        client.subscribe(lock_topic)
        logging.info(f"Subscribed to topic: {call_topic}")


def on_publish(client, userdata, mid, reason_code, properties):
    logging.info(f"message published {mid}")


def send_mqtt_message(input):
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="door-bot", protocol=mqtt.MQTTv5)
    mqttc.connect(mqtt_url, mqtt_port)
    mqttc.loop_start()
    msg_info = mqttc.publish(state_topic, input, qos=0)
    logging.info(f"Message is sent: {msg_info}")
    mqttc.disconnect()
    mqttc.loop_stop()


def start_mqtt():
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="door-call-bot", protocol=mqtt.MQTTv5)
    mqttc.on_connect = on_connect
    mqttc.on_message = on_message
    mqttc.on_subscribe = on_subscribe
    mqttc.on_unsubscribe = on_unsubscribe
    mqttc.on_publish = on_publish

    mqttc.user_data_set([])
    logging.info("mqtt server started")
    mqttc.connect(mqtt_url, mqtt_port)
    mqttc.loop_forever()


if __name__ == '__main__':
    logging.info("Starting Telegram bot...")
    logging.info(f"Allowed chat ids: {chat_list}")
    print(chat_list)
    print(type(chat_list[0]))
    application = ApplicationBuilder().token(bot_token).build()
    application.add_handler(CommandHandler('start', start, filters=filters.Chat(chat_list)))
    application.add_handler(CommandHandler('open', open_door, filters=filters.Chat(chat_list)))
    application.add_handler(
        CommandHandler('open_on_next_call', open_on_next_call_func, filters=filters.Chat(chat_list)))
    application.add_handler(CommandHandler('drop', drop_call, filters=filters.Chat(chat_list)))
    application.add_handler(MessageHandler(None, callback=restrict))

    # Start log monitoring in a separate thread
    multiprocessing.Process(target=start_mqtt, daemon=True).start()
    # Run bot polling in the main thread
    application.run_polling()
