main_dialog_id = 12345

# Commands (the same in webhook)
SET_PAUSE_COMMAND = "Поставить на паузу"
REMOVE_PAUSE_COMMAND = "Снять с паузы"
BLOCK_DIALOG_COMMAND = "Заблокировать"
UNBLOCK_DIALOG_COMMAND = "Разблокировать"
INIT_MASSAGE_COMMAND = "Инициировать"
START_SYNC_COMMAND = "Начать"
RESTART_SYNC_COMMAND = "Возобновить"
STOP_SYNC_COMMAND = "Остановить"
STATUS_SYNC_COMMAND = "Статус"

result = {
    "dialog_id": main_dialog_id,
    "message_type": "output",
}

request = args.get("request") if args.get("request") and args.get("request") != "none" else {}

action_command = request.get("command") if request.get("command") else {}

tg_message = request.get("message") if request.get("message") else {}

text = ""

try:

    if not action_command and not tg_message:
        raise Exception(f"Unknown request: {request}")

    # message from telegram
    if tg_message:

        if not tg_message.get("from").get("is_bot"):

            data = {
                "message_id": tg_message["message_id"],
            }

            # message from General topic
            if not tg_message.get("message_thread_id"):

                sync_commands = {
                    START_SYNC_COMMAND: "START SYNC",
                    STOP_SYNC_COMMAND: "STOP SYNC",
                    STATUS_SYNC_COMMAND: "STATUS SYNC",
                    RESTART_SYNC_COMMAND: "RESTART SYNC",
                }

                text = tg_message.get("text", "")

                if text and text in sync_commands:
                    text = sync_commands[text]

                    result["message_type"] = "input"

                else:

                    text = f"User message: {text}. Ignore."

            # message from dialog topic
            elif tg_message.get("text"):

                state_commands = [
                    SET_PAUSE_COMMAND,
                    BLOCK_DIALOG_COMMAND,
                    REMOVE_PAUSE_COMMAND,
                    UNBLOCK_DIALOG_COMMAND,
                    INIT_MASSAGE_COMMAND
                ]

                data["text"] = tg_message["text"]
                data["topic_id"] = tg_message["message_thread_id"]

                if tg_message.get("text") in state_commands:
                    text = str({
                        "event": "NEW_TELEGRAM_COMMAND_MESSAGE_EVENT",
                        "data": data
                    })

                else:
                    text = str({
                        "event" : "NEW_TELEGRAM_TEXT_MESSAGE_EVENT",
                        "data": data
                    })

            elif tg_message.get("photo"):

                photo = tg_message["photo"][-1]

                data["file_id"] = photo["file_id"]
                data["topic_id"] = tg_message["message_thread_id"]

                if tg_message.get("caption"):
                    data["caption"] = tg_message["caption"]

                text = str({
                    "event" : "NEW_TELEGRAM_PHOTO_MESSAGE_EVENT",
                    "data": data
                })

            elif tg_message.get("voice"):

                voice = tg_message["voice"]

                data["file_id"] = voice["file_id"]
                data["topic_id"] = tg_message["message_thread_id"]

                if tg_message.get("caption"):
                    data["caption"] = tg_message["caption"]

                text = str({
                    "event" : "NEW_TELEGRAM_VOICE_MESSAGE_EVENT",
                    "data": data
                })

            else:
                raise Exception(f"Unknown message from group member: {tg_message}")

        else:
            # Ignore
            text = f"Bot's message. Ignore."

    if action_command:

        if action_command == "run_checking":

            text = "RUN_CHECKING_DONT_SEND_MANUALY"

        elif action_command == "clean_dialog":

            text = "CLEAN_DIALOG_DONT_SEND_MANUALY"

        elif action_command == "delete_message":

            text = str({
                "event": "DELAYED_COMMAND_EVENT",
                "data": {
                    "command": action_command,
                    "message_id": request.get("message_id")
                }
            })

        elif action_command == "restart_app":

            text = "RESTART SYNC"

            result["message_type"] = "input"

        elif action_command == "init_message":

            result = {
                "dialog_id": request.get("dialog_id"),
                "message_type": "notification"
                }
            text = "Продолжи диалог"

        else:

            result = {
                "dialog_id": request.get("dialog_id"),
                "message_type": "forwarded_output",
            }

            if request.get("text"):
                text = request.get("text")

            if action_command == "send_text":

                result["content_type"] = "text"

            elif action_command == "send_image":

                result["content_type"] = "image"

                result["image_url"] = request.get("url")

            elif action_command == "send_audio":

                result["content_type"] = "audio"

                result["audio_url"] = request.get("url")
            else:
                raise Exception(f"Command {action_command} not recognized")

except Exception as e:

    text = f"WEBHOOK_EXCEPTION: {str(e)}"

result["text"] = text