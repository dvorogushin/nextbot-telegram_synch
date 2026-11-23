from datetime import datetime
from functools import wraps
from pprint import pformat
import requests
import copy
from datetime import datetime, timezone
import time
import math
import re
from typing import Any
import json
from requests import HTTPError
import ast
from typing import Any, Optional
from typing import Literal, Any
import traceback

#################
# VARIABLES
#################

DEBUG_MODE = False

SERVICE_NAME = "TELEGRAM_SYNC"
FUNC_NAME = "RUN_CHECKING_SCENARIO"

# Custom variables names
# dialog
LOGS_VAR_NAME = "logs"
TOPIC_URL = "topic_url"
#agent
DIALOGS_VAR_NAME = "dialogs"
STATUS_VAR_NAME = "status"
CONFIG_VAR_NAME = "configuration"
STATE_VAR_NAME = "state"

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

#status keyboard
DEFAULT_STATE_KEYBOARD = [
    [START_SYNC_COMMAND, RESTART_SYNC_COMMAND],
    [STOP_SYNC_COMMAND, STATUS_SYNC_COMMAND],
]
ACTIVE_STATE_KEYBOARD = [
    [STOP_SYNC_COMMAND, STATUS_SYNC_COMMAND]
]
NON_ACTIVE_STATE_KEYBOARD = [
    [START_SYNC_COMMAND, RESTART_SYNC_COMMAND, STATUS_SYNC_COMMAND]
]

LOG_RESULT = False


################################
#' module: logs.py
################################

logs = ""
debug_logs = ""

# to split logs from NB variable into lines use "➤" symbol
def _create_log(value):

    timestamp = datetime.now().isoformat(timespec="seconds")

    # Convert objects to a readable string
    if isinstance(value, str):
        message = value
    else:
        message = pformat(value)
    return f"➤[{timestamp}] {message}"


def debug(value):
    global debug_logs
    log = _create_log(f"[DEBUG] {value}")
    debug_logs += log + "\n"
    if DEBUG_MODE:
        print(log)


def log(value):
    global logs
    global debug_logs
    log = _create_log(f"[INFO] {value}")
    logs += log + "\n"
    debug_logs += log + "\n"
    print(log)


def log_err(value):
    global logs
    global debug_logs
    log = _create_log(f"[ERROR] {value}")
    logs += log + "\n"
    debug_logs += log + "\n"
    print(log)


def _truncate(value, max_length=300):
    text = str(value)
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text


def debug_io(max_result_length=300, max_param_length=300):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            debug(
                f"[CALL] {func.__name__} "
                f"args={_truncate(args, max_param_length)}, "
                f"kwargs={_truncate(kwargs, max_param_length)}"
            )

            try:
                result = func(*args, **kwargs)

                if isinstance(result, requests.Response):
                    body = _truncate(result.text, max_result_length)
                    debug(
                        f"[RETURN] {func.__name__}: "
                        f"status={result.status_code}, "
                        f"body={body}"
                    )
                else:
                    output = _truncate(result, max_result_length)
                    debug(f"[RETURN] {func.__name__}: {output}")

                return result

            except Exception as exc:
                log_err(f"{func.__name__}: {exc}")
                raise

        return wrapper

    return decorator

################################
#' module: nextbot_utils.py
################################

result = {}
variables = {}

def get_arg(name):
    return args.get(name) if args.get(name) and args.get(name) != 'none' else ""

def _get_var(type: str, key: str):
    variables = get_arg("variables") if get_arg("variables") and get_arg("variables") != "none" else {}
    type_vars = variables.get(type) if variables.get(type) else {}
    return type_vars.get(key) if type_vars.get(key) else {}

def get_dialog_var(key: str):
    return _get_var("dialog", key)

def get_agent_var(key: str):
    return _get_var("agent", key)

def now():
    return datetime.now(timezone.utc).isoformat()

# Build 'result' variable
class ResultBuilder:
    def __init__(self, save_debug_logs = False):
        self.result = {}
        self.MAX_SAVED_LOG_SIZE = 25_000
        self.save_debug_logs = save_debug_logs

    def send_message(self, value):
        if not isinstance(value, str):
            log_err("[IGNORED] send_message value should not be empty and string")
            return self

        self.result["send_message"] = value
        return self

    def silent(self, value):
        if value:
            self.result["silent"] = True
        return self

    def pause(self, value):
        if value:
            self.result["pause"] = True
        return self

    def block_user(self, value):
        if value:
            self.result["block_user"] = True
        return self

    def tool_result(self, value):
        if isinstance(value, str):
            self.result["tool_result"] = value
        else:
            self.result["tool_result"] = pformat(value)
        return self

    def notify_admin(self, value):
        if not isinstance(value, dict):
            log_err("[IGNORED] notify_admin value should be a dict")
            return self

        self.result["notify_admin"] = value
        self.result["notify_admin"].setdefault("messager", "telegram")

        return self

    def variables(self, value):
        if not isinstance(value, dict):
            log_err("[IGNORED] variables value should not be empty and dict")
            return self

        self.result.setdefault("variables", {}).update(value)
        return self

    def build(self):

        output = copy.deepcopy(self.result)
        output.setdefault("variables", {})
        output["variables"].pop(LOGS_VAR_NAME, None)
        if LOG_RESULT:
            log(f"[RESULT] {output}")
        else:
            log(f"[RESULT] LOG_RESULT: {LOG_RESULT}")


        previous_logs = get_dialog_var(LOGS_VAR_NAME)

        # save debug logs or info logs
        logs_to_save = debug_logs if self.save_debug_logs or DEBUG_MODE else logs
        combined = "\n".join(
            value for value in (previous_logs, logs_to_save) if value
        )
        self.result.setdefault("variables", {})
        self.result["variables"][LOGS_VAR_NAME] = combined[-self.MAX_SAVED_LOG_SIZE:]

        return self.result


def update_status_var():
    state = get_agent_var(STATUS_VAR_NAME)
    state.update({"updated": now()})
    return state

def stop_checking():

    state = get_agent_var(STATUS_VAR_NAME)
    state.update({"running": False})
    return state

# def to_superscript(text: str) -> str:
#     superscript_map = str.maketrans(
#         "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.()+-=",
#         "ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖᑫʳˢᵗᵘᵛʷˣʸᶻᴬᴮᶜᴰᴱᶠᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿˢᵀᵁⱽᵂ⁰¹²³⁴⁵⁶⁷⁸⁹ᐧ⁽⁾⁺⁻⁼"
#     )
#
#     return text.translate(superscript_map)

def to_superscript(text: str) -> str:
    superscript_map = str.maketrans({
        "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ",
        "e": "ᵉ", "f": "ᶠ", "g": "ᵍ", "h": "ʰ",
        "i": "ⁱ", "j": "ʲ", "k": "ᵏ", "l": "ˡ",
        "m": "ᵐ", "n": "ⁿ", "o": "ᵒ", "p": "ᵖ",
        "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ",
        "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ",
        "z": "ᶻ",
        "A": "ᴬ", "B": "ᴮ", "C": "ꟲ", "D": "ᴰ",
        "E": "ᴱ", "F": "ꟳ", "G": "ᴳ", "H": "ᴴ",
        "I": "ᴵ", "J": "ᴶ", "K": "ᴷ", "L": "ᴸ",
        "M": "ᴹ", "N": "ᴺ", "O": "ᴼ", "P": "ᴾ",
        "R": "ᴿ", "T": "ᵀ", "U": "ᵁ", "V": "ⱽ",
        "W": "ᵂ",
        "0": "⁰", "1": "¹", "2": "²", "3": "³",
        "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷",
        "8": "⁸", "9": "⁹",
        ".": "˙", "+": "⁺", "-": "⁻", "=": "⁼",
        "(": "⁽", ")": "⁾",
    })

    return text.translate(superscript_map)


def translate(text, source="kk", target="ru"):
    url = "https://api.mymemory.translated.net/get"

    params = {
        "q": text,
        "langpair": f"{source}|{target}",
        # "de": "your_email@example.com"  # uncomment and fill real email to increase limits up to 50_000 chars/day

    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    data = response.json()

    if data["responseStatus"] != 200:
        raise Exception(data["responseDetails"])

    return data["responseData"]["translatedText"]

################################
#' module: config.py
################################

class Config:

    @staticmethod
    def get_chat_id():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("chat_id").get("value")

    @staticmethod
    def get_bot_token(role):
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("bots_token").get(role)

    @staticmethod
    def get_email():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("credentials").get("email")

    @staticmethod
    def get_password():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("credentials").get("password")

    @staticmethod
    def get_webhook_url():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("webhook_url")

    @staticmethod
    def get_max_empty_iterations():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("max_empty_iterations").get("qnty")

    @staticmethod
    def get_main_dialog_id():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("main_dialog").get("id")

    @staticmethod
    def get_triggers_scenario_group():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("scenarios").get("triggers_group").get("value")

    @staticmethod
    def get_trigger_scenarios_ids():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("scenarios").get("trigger_scenarios_ids")

    @staticmethod
    def get_sub_agents_hashes():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("sub_agents").get("hashes") or []

    @staticmethod
    def get_checking_scenario_id():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("scenarios").get("checking_scenario_id")

    @staticmethod
    def get_restart_scenario_id():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("scenarios").get("restart_scenario_id")

    @staticmethod
    def get_max_auto_restart_qnty():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("max_auto_restart_qnty")

    @staticmethod
    def get_project_bot():
        config = get_agent_var(CONFIG_VAR_NAME)
        return config.get("project_bot")

################################
#' module: exceptions.py
################################

class AppException(Exception):
    pass

class InternalException(AppException):
    pass

class RetryExcludableException(AppException):
    def should_be_raise(self, response):
        return False

class ExternalException(AppException):
    message = "Возникла проблема"
    def get_massage(self) -> str:
        return self.message
    def __init__(self, internal_message):
        super().__init__(internal_message)

class NotAuthorizedException(ExternalException, RetryExcludableException):
    def __init__(self):
        super().__init__("Не удалось авторизоваться в сервисе")
        self.message = f"Не удалось авторизоваться в сервисе"

    def should_be_raise(self, response):
        return response.status_code == 401


# Telegram

class TopicNotModifiedException(InternalException, RetryExcludableException):

    def should_be_raise(self, response):

        data = response.json()

        return data.get("description") == "Bad Request: TOPIC_NOT_MODIFIED"


class MessageNotModifiedException(InternalException, RetryExcludableException):

    def should_be_raise(self, response):

        try:
            data = response.json() or {}
        except (ValueError, requests.exceptions.JSONDecodeError):
            data = {}

        return "Bad Request: message is not modified" in (data.get("description") or "")


class TooManyRequestsException(InternalException, RetryExcludableException):

    def __init__(self):
        super().__init__("Too many requests")

    def should_be_raise(self, response):

        data = response.json()

        return (
                not data.get("ok")
                and data.get("error_code") == 429
                and "Too Many Requests: retry after" in data.get("description")
        )

# class UnreachableTelegramFileException(InternalException, RetryExcludableException):
#
#     def should_be_raise(self, response):
#
#         return response.status_code in (400, 401, 403, 404)

class MessageToDeleteNotFoundException(InternalException, RetryExcludableException):

    def should_be_raise(self, response):

        try:
            data = response.json() or {}
        except (ValueError, requests.exceptions.JSONDecodeError):
            data = {}

        return data.get("description") == 'Bad Request: message to delete not found'


# class FailedToGetContentException(InternalException):
#     def __init__(self):
#         super().__init__("Failed to get content")

################################
#' module: retryer.py
################################

REQUEST_ATTEMPTS = 10

def retry(attempts=REQUEST_ATTEMPTS, timeout=10, delay_step:int=3, exclude=None):

    if exclude is None:
        exclude = []

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):

            # Use timeout from kwargs if provided, otherwise decorator default
            current_timeout = kwargs.pop("timeout", timeout)

            retry_attempts = kwargs.pop("retry_attempts", attempts)

            kwargs.pop("retry_exclude", None)

            delay = delay_step
            last_response = None
            last_exception = None

            for attempt in range(1, retry_attempts + 1):
                debug(f"attempt {attempt}/{retry_attempts}")
                try:
                    response = func(
                        *args,
                        timeout=current_timeout,
                        **kwargs,
                    )

                    last_response = response

                    for exception in exclude:
                        if exception().should_be_raise(response):
                            raise exception()

                    response.raise_for_status()
                    return response


                except requests.exceptions.Timeout as exc:
                    last_exception = exc

                    log_err(f"[IGNORED] Timeout: {current_timeout}")

                    current_timeout += 15


                except requests.exceptions.HTTPError as exc:
                    last_exception = exc

                    log_err(f"[IGNORED] {exc}")

                    time.sleep(delay)

                    delay += delay_step


                except requests.exceptions.RequestException as exc:
                    last_exception = exc
                    log_err(f"[IGNORED] {exc}")

                    time.sleep(delay)

                    delay += delay_step

                except Exception:

                    raise

            if last_response is not None:
                try:
                    last_response = last_response.json()
                except ValueError:
                    pass

            if last_exception is not None:
                raise last_exception

            raise RuntimeError(f"Can't reach resource.{last_response}")

        return wrapper

    return decorator

################################
#' module: tg_message.py
################################

class TelegramMessage:

    def __init__(
            self,
            text="",
            role="",
            type=None,
            source_url="",
            tags=None,
            hist_date="",
            origin = None,
            translated_text: str | None = None,
            flag: str | None = None,
            has_errors = False
    ):
        self.text = text
        self.role = role
        self.type = type
        self.source_url = source_url
        self.tags = tags or []
        self.hist_date = hist_date
        self.origin = origin
        self.translated_text = translated_text
        self.flag = flag
        self.has_errors = has_errors


    def get(self, key, default=None):
        return getattr(self, key, default)

    def build_message_text(self, new_text = None):

        text = new_text if new_text is not None else self.text

        if self.translated_text:
            text = self.translated_text

        if self.has_errors:
            text = "<s>" + text + "</s>"

        if self.flag:
            text = self.flag + " " + text

        if self.hist_date:
            text += "\n" + self.hist_date

        if self.tags:
            text += "\n" + " ".join(f"#{tag}" for tag in self.tags)

        return text


    @staticmethod
    def create_from(message = None):

        if message is None:
            return None

        role_client = "client"
        role_assistant = "assistant"
        role_manager = "manager"

        def _define_role(message):

            match message["role"]:
                case "user":
                    return role_client
                case "assistant":
                    if message['tags'] and "manager_message" in message['tags']:
                        return role_manager
                    else:
                        return role_assistant
            return None

        def _to_superscript_date(d: datetime) -> str:
            superscript = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
            dot = "ᐧ"
            return d.strftime(f"%d{dot}%m{dot}%y").translate(superscript)

        def _is_past_date(d: datetime) -> bool:
            now = datetime.now(timezone.utc)
            return d.date() != now.date() and abs(now - d).total_seconds() > 3600


        KAZAKH_CHARS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")

        def _is_kazakh(text: str) -> bool:
            return any(char in KAZAKH_CHARS for char in text)


        role = _define_role(message)
        if not role:
            return None

        text = message.get("content")

        obj = TelegramMessage(
            text=text,
            role=role,
            origin=message
        )
        if message.get("image_urls"):
            obj.type = "image"
            obj.source_url = message["image_urls"][0]
        elif message.get("audio_url"):
            obj.type = "audio"
            obj.source_url = message["audio_url"]
        else:
            obj.type = "text"

        if role == role_manager:
            obj.tags.append("manager")

        if ({"input_comment_message", "output_comment_message"}
                & set(message.get("tags") or [])):
            obj.tags.append("comment")

        created_date = datetime.fromisoformat(message.get("date"))
        if _is_past_date(created_date):
            obj.hist_date = _to_superscript_date(created_date)

        if _is_kazakh(obj.text):
            try:
                obj.translated_text = translate(text)
                obj.flag = "🇰🇿"
            except Exception as e:
                log_err(f"[IGNORED] Can't translate text: {e}")

        if message.get("error_code"):
            obj.has_errors = True

        return obj

################################
#' module: tg_topic.py
################################

class TelegramTopic:

    short_names = {
        "instagram": "inst",
        "telegramm": "tg",
        "AvitoPro": "avt",
        "Avito": "avt"
    }

    DEFAULT_EMOJI = "5417915203100613993" # 💬
    PAUSED_EMOJI = "5379748062124056162"  # ❗️
    BANNED_EMOJI = "5386395194029515402"  # 🏴‍☠️

    DEFAULT_KEYBOARD = [[SET_PAUSE_COMMAND, BLOCK_DIALOG_COMMAND, INIT_MASSAGE_COMMAND]]
    PAUSED_KEYBOARD = [[REMOVE_PAUSE_COMMAND, BLOCK_DIALOG_COMMAND, INIT_MASSAGE_COMMAND]]
    BANNED_KEYBOARD = [[UNBLOCK_DIALOG_COMMAND, INIT_MASSAGE_COMMAND]]

    def __init__(
            self,
            user = None,
    ):
        self.user = user
        self.dialog_id = 0
        self.user_id = user.get("user_id")
        self.messenger = user.get("from_messenger")
        self.user_name = user.get("user_name")
        self.user_messenger_name = user.get("user_name")
        self.topic_name = user.get("user_name")
        self.paused = user.get("paused")
        self.banned = user.get("banned")
        self.spent_bucks = 0
        self.spent_botcoins = 0
        self.id = 0
        self.short_messenger_name = self.short_names.get(
            self.messenger,
            ""
        )
        self.info_message_id = 0
        self.emoji_id = self.DEFAULT_EMOJI
        self.reply_keyboard = self.DEFAULT_KEYBOARD
        self.props = {}
        self.chat_id = user.get("chat_id") or ""


    def __getitem__(self, key):
        return getattr(self, key)

    def __str__(self):
        return str(self.user_name)

    def get(self, key, default=None):
        return getattr(self, key, default)

    # def get_topic_name(self):
    #     # 🔺 🔻 "⏸ ⛔" - emoji
    #     ⏸ ⏸ ⏯
    #     return self.name + " " + to_superscript(self.short_messenger_name or self.messenger)

    def get_url(self):

        c_id = Config.get_chat_id()

        c = c_id.removeprefix("-100")

        return f"https://t.me/c/{c}/{self.id}"

    def get_image_url(self):
        if self.messenger == "AvitoPro":
            return self.props.get("imageAd")
        elif self.user.get("avatar_url"):
            return self.user.get("avatar_url")
        return None

    def create_info_message(self):

        strings = []

        if self.banned:
            strings.append("⛔")
        elif self.paused:
            strings.append("⏸")

        bc = self.spent_botcoins
        usd = self.spent_bucks




        nb_link = f'<a href="https://rus.nextbot.ru/dialogs/{self.dialog_id}">НБ</a>'
        tg_link = f'<a href="{self.get_url()}">tg</a>'

        if self.messenger == "telegramm":
            if bc:
                strings.append(f"{to_superscript("bc")}   {self.spent_botcoins}")
            if usd:
                strings.append(f"{to_superscript("usd")}  {self.spent_bucks}")
            strings.append(f"{to_superscript("user")} @{self.user_name}\n")
            strings.append(f'Профиль: <a href="https://t.me/{self.user_name}">telegram</a>')
            strings.append(f"Диалог: {nb_link}")

        if self.messenger == "instagram":
            if bc:
                strings.append(f"{to_superscript("bc")}   {self.spent_botcoins}")
            if usd:
                strings.append(f"{to_superscript("usd")}  {self.spent_bucks}")
            strings.append(f"{to_superscript("user")} {self.user_name}\n")
            strings.append(f'Профиль: <a href="https://instagram.com/{self.user_name}">instagram</a>')
            strings.append(f'Диалоги: <a href="https://instagram.com/direct/t/{self.user_id}">instagram</a> / {nb_link}')

        if self.messenger == "AvitoPro":
            strings.append(f"{self.props.get("titleAd")}")
            strings.append(f"{self.props.get("priceAd")}")
            strings.append(f'<a href="{self.props.get("urlAd")}">{self.props.get("itemId")}</a>')
            strings.append("")
            if bc:
                strings.append(f"{to_superscript("bc")}   {self.spent_botcoins}")
            if usd:
                strings.append(f"{to_superscript("usd")}  {self.spent_bucks}")
            strings.append(f"{to_superscript("user")} {self.props.get("clientUserId")}")
            avito_dialog_link = f'<a href="https://www.avito.ru/profile/messenger/channel/{self.chat_id}">Авито</a>'
            strings.append(f"{to_superscript("dialogs")} {avito_dialog_link} / {nb_link} / {tg_link}")
            strings.append("")
            strings.append(f"#{self.user_messenger_name.replace(" ", "_")}")


        # if self.banned:
        #     strings.append("\n#banned")
        # elif self.paused:
        #     strings.append("\n#paused")

        return "\n".join(strings)

    @staticmethod
    def create_from(user, dialog_id):

        def _round(number):
            return  math.ceil(number * 100) / 100

        obj = TelegramTopic(user)

        obj.dialog_id = dialog_id

        obj.spent_bucks = _round(user.get("daily_spent_bucks"))

        obj.spent_botcoins = _round(
            math.fsum(
                amount
                for key, values in user.get("spendings").items()
                if key != "__bucks_by_date__"
                for amount in values.values()
            ) * 100
        )

        if user.get("additional_properties_messenger"):
            obj.props = user.get("additional_properties_messenger")

        if obj.messenger == "instagram":
            inst_name = user.get("additional_properties_messenger").get("instagramName")
            if inst_name:
                obj.user_messenger_name = inst_name

        # obj.topic_name = obj.user_messenger_name + " " + to_superscript(obj.short_messenger_name or obj.messenger)
        obj.topic_name = obj.user_messenger_name

        # warning emoji if dialog has errors
        if user.get("tags") and "has_error" in user.get("tags"):
            obj.topic_name = "⚠️ " + obj.topic_name

        obj.emoji_id = obj.BANNED_EMOJI if obj.banned \
            else obj.PAUSED_EMOJI if obj.paused \
            else obj.DEFAULT_EMOJI

        obj.reply_keyboard = obj.BANNED_KEYBOARD if obj.banned \
            else obj.PAUSED_KEYBOARD if obj.paused \
            else obj.DEFAULT_KEYBOARD

        return obj

################################
#' module: bots.py
################################

class TelegramBot:
    """Base class for Telegram bots."""

    def __init__(self, token: str, role: str):
        self.token = token
        if not self.token:
            raise InternalException("Token not provided")
        self.chat_id = Config.get_chat_id()
        if not self.chat_id:
            raise InternalException("Chat id not provided")
        self.role = role or ""
        self.base_url = "https://api.telegram.org/bot{token}/"
        self.session = requests.Session()
        self.topic_id = 0
        self.retry_excluded_exceptions = [TooManyRequestsException]
        self.timeout = 15


    @debug_io()
    def _request(self, method: str, http_method: str, **kwargs):

        retry_excluded_exceptions = self.retry_excluded_exceptions.copy()

        if retry_exclude := kwargs.pop("retry_exclude", None):
            retry_excluded_exceptions.append(retry_exclude)

        @retry(attempts=3, timeout=self.timeout, delay_step=5, exclude=retry_excluded_exceptions)
        def _retry_request(http_method: str, url: str, **kwargs):
            return self.session.request(
                method=http_method,
                url=url,
                **kwargs
            )

        url = self.base_url.format(token=self.token) + method

        kwargs.setdefault("timeout", self.timeout)

        try:
            response = _retry_request(http_method, url, **kwargs)

        except Exception as exc:
            response = getattr(exc, "response", None)

            if response is not None:
                try:
                    data = response.json()
                    log_err(f"Telegram error: {data}")
                except ValueError:
                    pass

            raise

        return response.json()


    @debug_io()
    def _get(self, method: str, params: dict | None = None):

        return self._request(
            method,
            "GET",
            params=params or {},
        )

    @debug_io()
    def _post(
            self,
            method: str,
            payload: dict,
            disable_preview: bool = True,
            reply_keyboard=None,
            **kwargs
    ):

        payload = payload.copy()

        payload["chat_id"] = kwargs.pop("chat_id", self.chat_id)

        topic_id = kwargs.pop("topic_id", self.topic_id)

        if topic_id:
            payload["message_thread_id"] = topic_id

        payload["link_preview_options"] = {
            "is_disabled": disable_preview
        }

        parse_mode = kwargs.pop("parse_mode", None)
        if parse_mode:
            payload["parse_mode"] = parse_mode

        if reply_keyboard:
            payload["reply_markup"] = {
                "keyboard": [
                    [{"text": button} for button in row]
                    for row in reply_keyboard
                ],
                "resize_keyboard": True,
                "one_time_keyboard": False
            }

        debug(f"Bot: {self.role}. Payload: {payload}")

        # JSON by default, or form-data when files are provided.
        request_data = {"json": payload}

        if "files" in kwargs:
            if "reply_markup" in payload:
                payload["reply_markup"] = json.dumps(payload["reply_markup"])

            request_data = {"data": payload}

        return self._request(
            method,
            "POST",
            **request_data,
            **kwargs
        )

    def send_text(
            self,
            text: str = "",
            disable_preview: bool = True,
            **kwargs
    ):
        log("Sending text message")

        method = "sendMessage"

        payload: dict[str, Any] = {
            "text": text,
        }

        return self._post(method, payload, disable_preview=disable_preview, **kwargs)

    def _send_photo(self, message: TelegramMessage, send_link_if_error: bool = True, **kwargs):

        log(f"Sending photo message")

        def _is_image_filename(text):
            return bool(re.fullmatch(r'[^/\\\s]+\.(?:jpg|png)', text, re.IGNORECASE)) or text == "[image]"

        method = "sendPhoto"

        text = message.get("text")

        caption = text if text and not _is_image_filename(text) else ""

        source_url = message.get("source_url")

        try:
            # Download the image
            image = requests.get(source_url, timeout=15)

            image.raise_for_status()

        except HTTPError as exc:

            status_code = exc.response.status_code
            if status_code not in (400, 401, 403, 404) and not send_link_if_error:
                raise

            log_err(f"[IGNORED] {exc}. Resent photo as link")

            link = f'[<a href="{source_url}">image</a>]'

            text = link if not caption else link + "\n" + text

            message_text = message.build_message_text(text)

            return self.send_text(
                message_text,
                parse_mode="HTML",
                disable_preview=False,
                **kwargs)

        data = {
            "caption": message.build_message_text(caption),
        }

        file = {
            "photo": ("image.png", image.content, "image/png"),
        }

        return self._post(method, data, files=file, **kwargs)


    def _send_voice(self, message: TelegramMessage, **kwargs):

        def _is_voice_filename(text: str) -> bool:
            if not isinstance(text, str):
                return False

            pattern = r'^https?://.+\.(?:mp3|ogg|oga|wav|m4a|aac|flac|opus)(?:\?.*)?$'

            return bool(re.match(pattern, text, re.IGNORECASE))

        log(f"Sending voice message")

        method = "sendVoice"

        text = message.get("text")

        source_url = message.get("source_url")

        caption = text if text and not _is_voice_filename(text) else ""

        try:
            # Download the file

            voice = requests.get(source_url, timeout=15)

            voice.raise_for_status()

        except HTTPError as exc:

            # if can't download - send as link
            status_code = exc.response.status_code
            if status_code not in (400, 401, 404):
                raise

            log_err(f"[IGNORED] {exc}. Resent voice as link")

            link = f'[<a href="{source_url}">voice</a>]'

            text = link if not caption else link + "\n" + text

            message_text = message.build_message_text(text)

            return self.send_text(
                message_text,
                parse_mode="HTML",
                disable_preview=False,
                **kwargs)

        data = {
            "caption": message.build_message_text(caption),
        }
        file = {
            "voice": ("voice.oga", voice.content, "audio/ogg"),
        }

        return self._post(method, data, files=file, **kwargs)



    @staticmethod
    def send(message: TelegramMessage, topic: TelegramTopic, **kwargs):

        role = message.get("role")
        bot = TelegramBot(Config.get_bot_token(role), role)

        if not bot:
            return None

        bot.topic_id = topic.id

        message_type = message.get("type")

        match message_type:
            case "text":
                text = message.build_message_text()
                return bot.send_text(text, parse_mode="HTML", **kwargs)
            case "image":
                return bot._send_photo(message, **kwargs)
            case "audio":
                return bot._send_voice(message, **kwargs)


        return None


class AdminBot(TelegramBot):

    def __init__(self,
                 token: str = Config.get_bot_token("admin"),
                 role: str = "admin"):

        super().__init__(token, role)


    def _create_topic(self, name: str, emoji_id: str = ""):

        log(f"Creating topic for {name}")

        payload = {
            "name": name or "unknown",
            "icon_color": 16766590,
            "icon_custom_emoji_id": emoji_id
        }

        data = self._post("createForumTopic", payload)

        created_topic = data["result"]

        return created_topic["message_thread_id"]


    def _pin_message(self, message_id: int = 0):

        log(f"Pinning message for {message_id}")

        method = "pinChatMessage"

        payload = {
            "message_id": message_id,
            "disable_notification": True
        }

        return self._post(method, payload)


    def update_message_text(self, message_id, text, **kwargs):

        method = "editMessageText"

        payload = {
            "message_id": message_id,
            "text": text,
        }

        return self._post(method, payload, **kwargs)


    def prepare_topic(self, topic: TelegramTopic):
        if topic is None:
            raise InternalException("TelegramTopic not provided")

        log(f"Creating topic for {topic}")

        topic_id = self._create_topic(topic.topic_name, topic.emoji_id)

        self.topic_id = topic.id = topic_id

        # send image if present

        image_url = topic.get_image_url()

        if image_url:
            try:
                self._send_photo(
                    TelegramMessage(source_url=image_url),
                    send_link_if_error=False
                )

            except:
                log_err(f"[IGNORED] {image_url} is an invalid image")

        data = self.send_text(topic.create_info_message(), parse_mode="HTML")

        info_message_id = topic.info_message_id = data["result"]["message_id"]

        self._pin_message(info_message_id)

        return topic_id, info_message_id


    def update_dialog_state(self, topic: TelegramTopic):

        if not topic:
            raise InternalException("Topic not provided")

        log(f"Updating dialog state for topic {topic}")

        #update topic emoji

        payload = {
            "message_thread_id": topic.id,
            "icon_custom_emoji_id": topic.emoji_id,
            "name": topic.topic_name,
        }

        try:
            self._post(
                "editForumTopic",
                payload,
                retry_exclude=TopicNotModifiedException
            )
            log(f"Icon updated for topic {topic}")
        except TopicNotModifiedException:
            pass

        # update info message

        info_message = topic.create_info_message()

        try:
            self.update_message_text(
                topic.info_message_id,
                info_message,
                parse_mode="HTML",
                retry_exclude=MessageNotModifiedException
            )

            log(f"Info message updated for topic {topic}")

        except MessageNotModifiedException:
            pass

        return True


    def delete_message(self, message_id, **kwargs):

        if not message_id:
            raise InternalException("Message id not provided")

        log(f"Deleting telegram message {message_id}")

        method = "deleteMessage"

        payload = {
            "message_id": message_id
        }

        return self._post(method, payload, **kwargs)

    def get_file_url(self, file_id):

        if not file_id:
            raise InternalException("File id not provided")

        log(f"Getting file path for file_id {file_id}")

        method = "getFile"

        params = {
            "file_id": file_id
        }

        data =  self._get(method, params)
        file_path = data["result"]["file_path"]


        return f"https://api.telegram.org/file/bot{self.token}/{file_path}"


    @staticmethod
    def set_telegram_webhook():
        method = "setWebhook"
        bot = AdminBot(Config.get_bot_token("admin"), "admin")

        payload = {
            "url": Config.get_webhook_url(),
            "allowed_updates": ["message"],
            }

        return bot._post(method, payload)


    @staticmethod
    def send_report(text, keyboard=None, **kwargs):

        log(f"Send report message")

        bot = AdminBot(Config.get_bot_token("admin"), "admin")

        return bot.send_text(text, reply_keyboard=keyboard, **kwargs)


class ProjectBot(TelegramBot):
    def __init__(self,
                 token: str,
                 role: str):

        super().__init__(token, role)
        if not self.token:
            raise RuntimeError("Token not provided")

    @staticmethod
    def _send_message(reason: str, text: str):

        bot_data = Config.get_project_bot()

        bot = ProjectBot(
            token=bot_data["token"],
            role="project"
        )

        chat_id = bot_data.get(reason).get("chat_id")
        if not chat_id:
            raise RuntimeError(f"Chat id not provided: {chat_id}")

        topic_id = bot_data.get(reason).get("topic_id") or 0

        try:
            return bot.send_text(text, chat_id=chat_id, topic_id=topic_id, retry_attempts=1)

        except Exception as exc:

            log_err(f"[IGNORED] {exc}")

            return None


    @staticmethod
    def send_error(text: str):

        mes_text = (f"[{SERVICE_NAME}]\n"
                    f"{FUNC_NAME}\n"
                    f"{text}")

        return ProjectBot._send_message(
            "error",
            mes_text
        )

    @staticmethod
    def send_order(text: str):

        return ProjectBot._send_message(
            "order",
            text
        )

    @staticmethod
    def send_question(text: str):

        return ProjectBot._send_message(
            "question",
            text
        )

    @staticmethod
    def send_size_absent(text: str):

        return ProjectBot._send_message(
            "size_absent",
            text
        )

    @staticmethod
    def send_ad_absent(text: str):

        return ProjectBot._send_message(
            "ad_absent",
            text
        )

################################
#' module: dialogs.py
################################

class Dialogs:

    # structure
    #   {
    #     "id": 21047584,
    #     "updated": "2026-10-16T02:03:05.050443+00:00",
    #     "topic_id": 89,
    #     "last_message_id": 306265316
    #   }

    MAX_MESSAGES_HISTORY_QNTY = 150

    def __init__(self, dialogs = None):
        self.dialogs_db = dialogs or []

    def get_new_messages(self, dialog_id: int, messages: list, current_message: dict) -> list:

        dialog_obj = next(
            (
                dialog
                for dialog in self.dialogs_db
                if dialog["id"] == dialog_id
            ),
            None,
        )

        if dialog_obj is None:
            return messages[:self.MAX_MESSAGES_HISTORY_QNTY]

        last_message_id = dialog_obj.get("lm_id")

        if last_message_id is None:
            return messages[:self.MAX_MESSAGES_HISTORY_QNTY]

        return [
            message
            for message in messages
            if last_message_id < message["id"] <= current_message["id"]
        ][-self.MAX_MESSAGES_HISTORY_QNTY:]

        # id, content, role
        # assistant, tool, tool_cals, scenario, user,

    def get_dialogs(self):
        return self.dialogs_db

    def update_dialog_obj(self, dialog_id: int, message= None, topic_id: int=0, info_message_id: int=0) -> None:

        for dialog in self.dialogs_db:
            if dialog.get("id") == dialog_id:
                dialog["updated"] = now()
                if topic_id:
                    dialog["topic_id"] = topic_id
                if info_message_id:
                    dialog["im_id"] = info_message_id
                if message:
                    dialog["lm_id"] = message["id"]
                return

        new_dialog_obj = {
            "id": dialog_id,
            "updated": now(),
        }

        if message:
            new_dialog_obj["lm_id"] = message["id"]
        if topic_id:
            new_dialog_obj["topic_id"] = topic_id
        if info_message_id:
            new_dialog_obj["im_id"] = info_message_id

        self.dialogs_db.append(new_dialog_obj)

    def get_topic_data(self, dialog_id: int) -> tuple[int, int]:
        return next((
            (dialog["topic_id"], dialog["im_id"])
            for dialog in self.dialogs_db
            if dialog["id"] == dialog_id
        ), (0, 0))


    def get_dialog_id(self, topic_id: int) -> int | None:

        dialogs = self.get_dialogs()

        return next((
            dialog.get("id")
            for dialog in dialogs
            if dialog.get("topic_id") == topic_id
        ), None)

################################
#' module: nextbot_webhook.py
################################

class NextBotWebhook:
    def __init__(self):
        self.webhook_url = Config.get_webhook_url()
        if not self.webhook_url:
            raise InternalException("Webhook URL not found")

    @debug_io()
    @retry(attempts=5, timeout=15, delay_step=5)
    def _post(self, payload=None, timeout=10):

        api_url = self.webhook_url

        return requests.post(
            api_url,
            json=payload,
            timeout=timeout
        )
        # response.raise_for_status()
        # return response.json()


    @staticmethod
    def run_next_iteration():
        log(f"[REQUEST] Running next checking iteration")

        response = NextBotWebhook()._post({
            "command": "run_checking",
        })

        return response.json()

    @staticmethod
    def clean_dialog():
        log(f"[REQUEST] Clean dialog")

        response = NextBotWebhook()._post({
            "command": "clean_dialog",
        })

        return response.json()


    @staticmethod
    def send_text(dialog_id, text):

        log(f"[REQUEST] Sending text message into NB dialog: {dialog_id}")

        payload = {
            "command": "send_text",
            "text": text,
            "dialog_id": dialog_id
        }

        response = NextBotWebhook()._post(payload)

        return response.json()


    @staticmethod
    def send_image(dialog_id, url, caption : str = ""):

        log(f"[REQUEST] Sending image into NB dialog: {dialog_id}")

        payload = {
            "command": "send_image",
            "url": url,
            "text": caption,
            "dialog_id": dialog_id
        }

        response = NextBotWebhook()._post(payload)

        return response.json()


    @staticmethod
    def send_audio(dialog_id, url, caption : str = ""):

        log(f"[REQUEST] Sending audio into NB dialog: {dialog_id}")

        payload = {
            "command": "send_audio",
            "url": url,
            "text": caption,
            "dialog_id": dialog_id
        }

        response = NextBotWebhook()._post(payload)

        return response.json()

    @staticmethod
    def delete_message(message_id):

        log(f"[REQUEST] Sending delete command into NB for message: {message_id}")

        payload = {
            "command": "delete_message",
            "message_id": message_id
        }

        response = NextBotWebhook()._post(payload)

        return response.json()

    @staticmethod
    def restart_app():

        log(f"[REQUEST] Send restart command")

        payload = {
            "command": "restart_app",
        }

        response = NextBotWebhook()._post(payload)

        return response.json()


    @staticmethod
    def init_message(dialog_id):

        log(f"[REQUEST] Send restart command")

        payload = {
            "command": "init_message",
            "dialog_id": dialog_id
        }

        response = NextBotWebhook()._post(payload)

        return response.json()

################################
#' module: events.py
################################

class Events:

    event_names = [
        "NEW_TELEGRAM_TEXT_MESSAGE_EVENT",
        "NEW_TELEGRAM_PHOTO_MESSAGE_EVENT",
        "NEW_TELEGRAM_VOICE_MESSAGE_EVENT",
        "NEW_TELEGRAM_COMMAND_MESSAGE_EVENT",
        "DELAYED_COMMAND_EVENT"
    ]

    @staticmethod
    def check_telegram_event(message, dialogs: Dialogs) -> bool:

        def _handle_command_event():

            def _get_topic(dialog_id):

                user_data = nb_client.get_user_data(
                    dialog_id)

                topic = TelegramTopic.create_from(
                    user_data,
                    dialog_id)

                topic.id, topic.info_message_id = dialogs.get_topic_data(dialog_id)

                return topic

            command = data.get("text")

            if command == SET_PAUSE_COMMAND:

                nb_client.set_dialog_state(
                    dialog_id=dialog_id,
                    type="pause",
                    set=True)

                message_text = (
                    "Диалог поставлен на паузу. "
                    "Сообщения клиента будут видны, "
                    "но бот не будет реагировать.")

            elif command == REMOVE_PAUSE_COMMAND:

                nb_client.set_dialog_state(
                    dialog_id=dialog_id,
                    type="pause",
                    set=False)

                message_text = "Диалог снят с паузы"

            elif command == BLOCK_DIALOG_COMMAND:

                nb_client.set_dialog_state(
                    dialog_id=dialog_id,
                    type="bann",
                    set=True)

                message_text = ("Диалог заблокирован. "
                                "Новые сообщения не будут отображаться.")

            elif command == UNBLOCK_DIALOG_COMMAND:

                nb_client.set_dialog_state(
                    dialog_id=dialog_id,
                    type="bann",
                    set=False)

                message_text = "Диалог разблокирован."

            elif command == INIT_MASSAGE_COMMAND:

                nb_client.set_dialog_state(
                    dialog_id=dialog_id,
                    type="pause",
                    set=False)

                nb_client.set_dialog_state(
                    dialog_id=dialog_id,
                    type="bann",
                    set=False)

                NextBotWebhook.init_message(dialog_id)

                message_text = "Инициализировано сообщение ботом."

            else:
                raise InternalException(f"Unknown command {command}")

            # update_topic_state
            topic = _get_topic(dialog_id)

            bot.update_dialog_state(topic)

            resp = bot.send_text(
                message_text,
                topic_id=topic_id,
                reply_keyboard=topic.reply_keyboard
            )

            should_be_deleted_message_id = resp["result"]["message_id"]

            NextBotWebhook().delete_message(should_be_deleted_message_id)

            return


        try:
            content = message.get("content")

            obj = ast.literal_eval(content)

            event = obj.get("event")

            if event not in Events().event_names:
                return False

        except (ValueError, SyntaxError):
            return  False


        if any(event_name in content for event_name in Events().event_names):


            data = obj["data"]

            bot = AdminBot()

            if event == "DELAYED_COMMAND_EVENT":

                if data.get("command") == "delete_message":

                    try:
                        bot.delete_message(data.get("message_id"), retry_exclude=MessageToDeleteNotFoundException)
                    except MessageToDeleteNotFoundException as exc:
                        log_err(f"[IGNORED] {exc}")
                        pass

                return True

            topic_id = data.get("topic_id")

            dialog_id = dialogs.get_dialog_id(topic_id)

            if not dialog_id:
                raise InternalException(f"Dialog id not found in Dialogs by topic_id {topic_id}.")


            if event == "NEW_TELEGRAM_COMMAND_MESSAGE_EVENT":

                _handle_command_event()


            elif event == "NEW_TELEGRAM_TEXT_MESSAGE_EVENT":

                text = data.get("text")

                NextBotWebhook.send_text(dialog_id, text)


            elif data.get("file_id"):

                url = bot.get_file_url(data["file_id"])

                if event == "NEW_TELEGRAM_PHOTO_MESSAGE_EVENT":

                    NextBotWebhook.send_image(
                        dialog_id,
                        url,
                        data.get("caption"))

                elif event == "NEW_TELEGRAM_VOICE_MESSAGE_EVENT":

                    NextBotWebhook.send_audio(
                        dialog_id,
                        url,
                        data.get("caption"))

                else:
                    raise Exception("Unknown event with file_id")
            else:
                raise Exception("Should not be happen")

            # delete message on next iteration
            NextBotWebhook.delete_message(data.get("message_id"))

            return True
        return False

################################
#' module: nextbot_auth_client.py
################################

class AuthClient:
    def __init__(
        self,
        timeout: int = 15,
    ):

        self.base_url = "https://api.nextbot.ru"
        self.apikey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ2ZXJsa3F6dG9temh6bXd0enp0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE2ODk3MjAwMjYsImV4cCI6MjAwNTI5NjAyNn0.h7Jfmvv6X6sh0EfD9BiN0VFXeHp6aEc3tKVdi3OPrDc"
        self.login_endpoint = "/auth/v1/token?grant_type=password"
        self.refresh_endpoint = "/auth/v1/token?grant_type=refresh_token"
        self.agent_hash = get_arg("agentHash")
        if not self.agent_hash:
            raise RuntimeError("Agent hash not provided in agent variables")
        self.email = Config.get_email()
        self.password = Config.get_password()
        self.tokens = get_agent_var(STATE_VAR_NAME).get("auth_tokens") or {}
        self.access_token = self.tokens.get("access_token")
        self.refresh_token = self.tokens.get("refresh_token")
        self.expires_at = self.tokens.get("expires_at")
        self.updated = self.tokens.get("updated")
        self.retry_excluded_exceptions = [NotAuthorizedException]

        self.timeout = timeout
        self.session = requests.Session()

    def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send an authentication POST request."""
        headers = {
            "apikey": self.apikey,
        }

        if authorization:
            headers["Authorization"] = authorization

        @retry(attempts=3, timeout=self.timeout, delay_step=5)
        def retry_auth_post(payload, headers, timeout=self.timeout):

            return self.session.post(
                f"{self.base_url}{endpoint}",
                json=payload,
                headers=headers,
                timeout=timeout
            )

        response = retry_auth_post(payload, headers)

        response.raise_for_status()
        return response.json()

    def _save_tokens(self, data: dict[str, Any]) -> None:
        """Save authentication tokens."""
        access_token = data.get("access_token")

        if not access_token:
            raise ValueError(
                "Authentication response contains no access_token"
            )

        self.access_token = access_token

        # Update the refresh token if the API returns a new one.
        if data.get("refresh_token"):
            self.refresh_token = data["refresh_token"]

        self.expires_at = data.get("expires_at")
        self.updated = now()

    def login(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> str:
        """Log in using credentials and the API key as a Bearer token."""
        email = email or self.email
        password = password or self.password

        if not email or not password:
            raise ValueError("Email and password are required")

        data = self._post(
            endpoint=self.login_endpoint,
            payload={
                "email": email,
                "password": password,
            },
            authorization=f"Bearer {self.apikey}",
        )

        self._save_tokens(data)

        return self.access_token

    def refresh_access_token(self) -> str | None | Any:
        """Refresh the access token, falling back to login if the refresh token is invalid."""
        if not self.refresh_token:
            return self.login()

        try:
            data = self._post(
                endpoint=self.refresh_endpoint,
                payload={"refresh_token": self.refresh_token},
                authorization=f"Bearer {self.apikey}",
            )
        except requests.exceptions.HTTPError as exc:
            response = exc.response

            if response is not None:
                try:
                    data = response.json()
                except ValueError:
                    raise exc

                if (
                        data.get("code") == 400
                        and data.get("error_code") == "refresh_token_not_found"
                ):
                    return self.login()

            raise

        self._save_tokens(data)
        return self.access_token

    def get_token(self) -> str:
        """Return a valid access token, refreshing it if expired."""
        if not self.access_token:
            return self.login()

        if self.expires_at is not None:
            if time.time() >= self.expires_at - 30:
                return self.refresh_access_token()


        return self.access_token

    def get_tokens(self):
        return {
            "access_token": self.access_token or "",
            "refresh_token": self.refresh_token or "",
            "expires_at": self.expires_at or 0,
            "updated": self.updated or ""
        }

    def request(
        self,
        method: str,
        endpoint: str,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Send an authenticated request.

        Every request includes the apikey header.
        If a request returns 401, refresh the access token and retry once.
        """

        # Use custom base_url if provided, otherwise use self.base_url
        url = f"{(base_url or self.base_url).rstrip('/')}/{endpoint.lstrip('/')}"

        # Get a valid access token.
        token = self.get_token()

        # Preserve caller-provided headers.
        headers = dict(kwargs.pop("headers", {}))

        # Add required authentication headers.
        headers["apikey"] = self.apikey
        headers["Authorization"] = f"Bearer {token}"

        @retry(attempts=5, timeout=10, delay_step=5, exclude=self.retry_excluded_exceptions)
        def _retry_request(*args, **kwargs):

            response = self.session.request(
                **kwargs,
            )
            return response

        try:

            return _retry_request(
                method=method,
                url=url,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )

        except NotAuthorizedException as e:

            log_err(f"[HANDLED] {e}")

            token = self.refresh_access_token()

            headers["Authorization"] = f"Bearer {token}"

            return _retry_request(
                method=method,
                url=url,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )


    def get(
        self,
        endpoint: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Send an authenticated GET request."""
        return self.request("GET", endpoint, **kwargs)

    def post(
        self,
        endpoint: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Send an authenticated POST request."""
        return self.request("POST", endpoint, **kwargs)

    def put(
        self,
        endpoint: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Send an authenticated PUT request."""
        return self.request("PUT", endpoint, **kwargs)

    def patch(
        self,
        endpoint: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Send an authenticated PATCH request."""
        return self.request("PATCH", endpoint, **kwargs)

    def delete(
        self,
        endpoint: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Send an authenticated DELETE request."""
        return self.request("DELETE", endpoint, **kwargs)

    def logout(self) -> None:
        """Clear local authentication tokens."""
        self.access_token = None
        self.refresh_token = None
        self.expires_at = None

    def close(self) -> None:
        """Close the HTTP session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

################################
#' module: nextbot_client.py
################################

class NextBotClient(AuthClient):

    LIMIT = 200

    @debug_io()
    def _get_messages(self, dialog_id = None, last_message_id = None):

        if not dialog_id and not last_message_id:
            raise InternalException("Can't get messages: either dialog_id or last_message_id must be provided")

        endpoint = f"rest/v1/messages"

        params = {
            "select": "*",
            "order": "date.desc.nullslast,id.desc",
            "limit": self.LIMIT,
        }

        if dialog_id:
            params["dialog_id"] = f"eq.{dialog_id}"
        if last_message_id:
            params["id"] = f"gt.{last_message_id}"
            hashes = Config.get_sub_agents_hashes()
            hashes.append(self.agent_hash)
            params["agent_hash"] = f"in.({','.join(hashes)})"
            # params["agent_hash"] = f"eq.{self.agent_hash}"

        response = self.get(endpoint,params=params)
        response.raise_for_status()
        json_response = response.json()
        return json_response

    @debug_io()
    def _get_last_20_dialogs(self):
        endpoint = f"rest/v1/rpc/search_dialogs_without_messages_v2"
        response = self.post(
            endpoint,
            json={
                "p_agent_hash": self.agent_hash,
                "p_page" : 1,
                "p_per_page": 20
            }
        )
        response.raise_for_status()
        json_response = response.json()
        return json_response

    @debug_io()
    def get_dialog_messages(self, dialog_id):
        return self._get_messages(dialog_id=dialog_id)


    @debug_io()
    def get_default_last_message(self):

        last_20_dialogs = self._get_last_20_dialogs()

        for dialog in last_20_dialogs:

            messages = self._get_messages(dialog["dialog_data"]["id"])

            if messages:
                return messages[0]

        raise InternalException("Can't find non-empty dialog")


    @debug_io()
    def get_new_messages(self, last_message):

        return self._get_messages(last_message_id=last_message.get("id"))


    @debug_io()
    def get_dialog_data(self, dialog_id):

        endpoint = f"/rest/v1/dialogs?select=*&id=in.({dialog_id})"

        response = self.get(endpoint)

        json_response = response.json()

        return json_response


    @debug_io()
    def get_user_data(self, dialog_id):
        return self.get_dialog_data(dialog_id=dialog_id)[0]


    @debug_io()
    def get_agent_data(self):

        endpoint = f"/rest/v1/agents"

        response = self.get(endpoint,
                            params= {
                                "select":"*",
                                "agent_hash": "eq." + self.agent_hash,
                            })

        response.raise_for_status()

        json_response = response.json()

        return json_response

    @debug_io()
    def enable_trigger_scenarios_group(self, enable: bool):
        endpoint = f"/rest/v1/rpc/apply_agent_config_cas_v1"

        agent_data = self.get_agent_data()[0]

        version = agent_data.get("version")
        user_id = agent_data.get("user_id")

        scenarios_group = Config.get_triggers_scenario_group()

        scenarios_group.update({"enabled": enable})

        response = self.post(
            endpoint,
            headers={
                "content-profile": "agent_config"
            },
            json={
                "p_actor": "ui",
                "p_actor_user_id" : user_id,
                "p_agent_hash": self.agent_hash,
                "p_tool_name": "scenario.update_groups",
                "p_expected_version": int(version),
                "p_input":{
                    "count": 1
                },
                "p_updates": {
                    "scenario_groups": [scenarios_group]
                }})

        response.raise_for_status()

        json_response = response.json()

        return json_response

    @debug_io()
    def enable_trigger_scenarios(self, enable: bool = True):
        endpoint = f"/rest/v1/rpc/apply_agent_config_cas_v1"

        scenarios_ids = Config.get_trigger_scenarios_ids()

        agent_data = self.get_agent_data()[0]

        for scenario in agent_data.get("scenarios", []):
            for scenario_data in scenario.values():
                if scenario_data.get("scenarioId") in scenarios_ids:
                    scenario_data["enabled"] = enable

        version = agent_data.get("version")
        user_id = agent_data.get("user_id")

        response = self.post(
            endpoint,
            headers={
                "content-profile": "agent_config"
            },
            json={
                "p_actor": "ui",
                "p_actor_user_id": user_id,
                "p_agent_hash": self.agent_hash,
                "p_tool_name": "scenario.patch",
                "p_expected_version": int(version),
                "p_updates": {
                    "scenarios": agent_data.get("scenarios")
                }})

        response.raise_for_status()

        json_response = response.json()

        return json_response


    @debug_io()
    def is_trigger_scenarios_enabled(self):

        scenarios_ids = Config.get_trigger_scenarios_ids()

        agent_data = self.get_agent_data()[0]

        return all(
            scenario_data.get("enabled") is True
            for scenario in agent_data.get("scenarios", [])
            for scenario_data in scenario.values()
            if scenario_data.get("scenarioId") in scenarios_ids
        )

    @debug_io()
    def is_scenarios_enabled(self, ids) -> bool:

        agent_data = self.get_agent_data()[0]

        target_ids = {ids} if isinstance(ids, int) else set(ids)

        # target_ids = set(trigger_ids)
        # target_ids.add(checking_id)

        # Index scenario groups by ID
        scenario_groups = {
            group["id"]: group
            for group in agent_data.get("scenario_groups", [])
        }

        # Check all target scenarios
        for scenario_wrapper in agent_data.get("scenarios", []):
            for scenario in scenario_wrapper.values():
                scenario_id = scenario.get("scenarioId")

                if scenario_id not in target_ids:
                    continue

                # Check if scenario is enabled
                if not scenario.get("enabled", False):
                    return False

                # Check if its scenario group exists and is enabled
                group_id = scenario.get("scenarioGroupId")
                group = scenario_groups.get(group_id)

                if not group or not group.get("enabled", False):
                    return False

                # This target has been successfully checked
                target_ids.remove(scenario_id)

        # Return False if any target scenario wasn't found
        return not target_ids


    @debug_io()
    def enable_delay_in_scenario_id(self, ids: Any, enable: bool = True, delay_sec: int = 60):
        endpoint = f"/rest/v1/rpc/apply_agent_config_cas_v1"

        target_ids = {ids} if isinstance(ids, int) else set(ids)

        # scen_id = Config.get_checking_scenario_id()

        agent_data = self.get_agent_data()[0]

        for scenario in agent_data.get("scenarios", []):
            for scenario_data in scenario.values():
                if scenario_data.get("scenarioId") in target_ids:
                    scenario_data["delayed_execution"]["match"]["enabled"] = enable
                    if enable:
                        scenario_data["delayed_execution"]["match"]["delayMs"] = delay_sec * 1_000


        version = agent_data.get("version")
        user_id = agent_data.get("user_id")

        response = self.post(
            endpoint,
            headers={
                "content-profile": "agent_config"
            },
            json={
                "p_actor": "ui",
                "p_actor_user_id": user_id,
                "p_agent_hash": self.agent_hash,
                "p_tool_name": "scenario.update",
                "p_expected_version": int(version),
                "p_updates": {
                    "scenarios": agent_data.get("scenarios")
                }})

        response.raise_for_status()

        json_response = response.json()

        return json_response

    @debug_io()
    def set_agent_variable(self, name: str, value: dict) -> None:
        endpoint = f"/rest/v1/agents"

        agent_data = self.get_agent_data()[0]
        variable_values = agent_data.get("variable_values")
        variables_catalog = agent_data.get("variables_catalog")

        if name not in variable_values:
            variable_values[name] = {}

        variable_values[name]["value"] = value

        response = self.patch(
            endpoint,
            headers={
                "content-profile": "public"
            },
            params={
                "select": "*",
                "agent_hash": "eq." + self.agent_hash,
            },
            json={
                "variable_values": variable_values,
                "variables_catalog": variables_catalog,
            }
        )

        response.raise_for_status()

    @debug_io()
    def update_agent_variable(self, name: str, value: dict) -> None:
        endpoint = f"/rest/v1/agents"

        agent_data = self.get_agent_data()[0]
        variable_values = agent_data.get("variable_values")
        variables_catalog = agent_data.get("variables_catalog")

        if name not in variable_values:
            variable_values[name] = {}
            variable_values[name]["value"] = value
        else:
            variable_values[name]["value"].update(value)

        response = self.patch(
            endpoint,
            headers={
                "content-profile": "public"
            },
            params={
                "select": "*",
                "agent_hash": "eq." + self.agent_hash,
            },
            json={
                "variable_values": variable_values,
                "variables_catalog": variables_catalog,
            }
        )

        response.raise_for_status()

    @debug_io()
    def get_agent_variable(self, name: str) -> dict:

        agent_data = self.get_agent_data()[0]
        variable_values = agent_data.get("variable_values")
        return variable_values.get(name, {}).get("value", {})


    @debug_io()
    def clean_main_dialog(self):
        endpoint = f"api/dialogs/{self.agent_hash}"
        custom_base_url = "https://rus.nextbot.ru"
        response = self.post(
            endpoint,
            base_url=custom_base_url,
            json={
                "message":"/restart"
            }
        )

        response.raise_for_status()

        json_response = response.json()

        return json_response

    # set paused / banned
    @debug_io()
    def set_dialog_state(
            self,
            dialog_id: int,
            type: Literal["pause", "bann"],
            set: bool,
    ) -> None:
        endpoint = "rest/v1/dialogs"

        if type == "pause":
            payload = {"paused": set}
        elif type == "bann":
            if set:
                payload = {"banned": True}
            else:
                payload = {
                    "banned": False,
                    "paused": False
                }

        else:
            raise ValueError(f"Invalid key {type}")

        response = self.patch(
            endpoint,
            headers={"content-profile": "public"},
            params={"id": "eq." + str(dialog_id)},
            json=payload,
        )

        response.raise_for_status()

    @debug_io()
    def update_dialog_variable(self, dialog_id, name: str, value: Any) -> None:
        endpoint = f"/rest/v1/dialogs"

        dialog_data = self.get_dialog_data(dialog_id)[0]
        variable_values = dialog_data.get("variable_values")

        if name not in variable_values:
            variable_values[name] = {}

        variable_values[name]["value"] = value
        variable_values[name]["updated_at"] = now()
        variable_values[name]["updated_by"] = "dialog_ui"

        response = self.patch(
            endpoint,
            headers={
                "content-profile": "public"
            },
            params={
                "id": "eq." + str(dialog_id),
            },
            json={
                "variable_values": variable_values,
            }
        )

        response.raise_for_status()

################################
#' function: run_checking.py
################################

#################
# CODE
#################

if not args.get("userId"):
    TEST_MODE = True
else:
    TEST_MODE = False

try:
    log(f"[BEGIN] `{FUNC_NAME}`")

    if TEST_MODE:
        log(f"[TEST_MODE] True")

    status = get_agent_var(STATUS_VAR_NAME)

    if status and status["running"]:

        handled_message_counter = 0

        nb_client = NextBotClient()


        last_message = (get_agent_var(STATE_VAR_NAME).get("last_message") or {}).get("message")

        # for first run getting last message from last 20 dialogs
        if not last_message:

            last_message = nb_client.get_default_last_message()

            nb_client.update_agent_variable(
                STATE_VAR_NAME, {
                    "last_message": {
                        "created": now(),
                        "message": last_message
                    },

            })

        new_messages = nb_client.get_new_messages(last_message)

        # nextbot variable (dialog_id -> topic_id, last_handled_message)
        dialogs = Dialogs(
            nb_client.get_agent_variable(DIALOGS_VAR_NAME)
        )

        downloaded_dialogs = []
        # topics with updated emoji and info message
        updated_state_topic_ids = []
        # topics with updated reply keyboard
        # new keyboard can be updated only by sending new non-deleted message
        updated_keyboard_topic_ids = []
        new_messages.reverse()

        admin_bot = AdminBot()

        # Логика: из каждого нового сообщения определяем диалог
        # по каждому диалогу проверяем историю и если есть не досланные сообщения - досылаем
        # не досланные сообщения: id сообщения больше последнего пересланного из Dialogs и меньше или равно текущему message
        # так как цикл по новым сообщениям, а проверка и досылка по каждому диалогу нового сообщения:
        # то в handled_dialog_ids складываем скачанные диалоги что-бы не скачивать повторно
        for message in new_messages:

            dialog_id = message["dialog_id"]

            if dialog_id == Config.get_main_dialog_id():

                # checks if operator message from telegram group
                if Events.check_telegram_event(message, dialogs):

                    handled_message_counter += 1

                    nb_client.update_agent_variable(STATE_VAR_NAME, {
                        "last_message": {
                            "created": now(),
                            "message": message }})

                continue

            all_dialog_messages, user_data = next(
                (
                    (dialog["messages"], dialog["user_data"])
                    for dialog in downloaded_dialogs
                    if dialog["id"] == dialog_id
                ), (None, None))

            if not all_dialog_messages:

                # download messages and user_data
                all_dialog_messages = nb_client.get_dialog_messages(dialog_id)

                user_data = nb_client.get_user_data(dialog_id)

                downloaded_dialogs.append({
                    "id": dialog_id,
                    "messages": all_dialog_messages,
                    "user_data": user_data
                })

            new_dialog_messages = dialogs.get_new_messages(dialog_id, all_dialog_messages, message)

            if not new_dialog_messages:
                continue

            tg_topic = TelegramTopic.create_from(user_data, dialog_id)

            new_dialog_messages.reverse()

            topic_id, info_message_id = dialogs.get_topic_data(dialog_id)

            if not topic_id:

                # create topic, create info message
                topic_id, info_message_id = admin_bot.prepare_topic(tg_topic)

                dialogs.update_dialog_obj(
                    dialog_id,
                    topic_id=topic_id,
                    info_message_id=info_message_id)

                nb_client.set_agent_variable(
                    DIALOGS_VAR_NAME,
                    dialogs.get_dialogs())

                updated_state_topic_ids.append(topic_id)

            else:

                tg_topic.id = topic_id
                tg_topic.info_message_id = info_message_id

            # update emoji and info message
            if topic_id not in updated_state_topic_ids:

                admin_bot.update_dialog_state(tg_topic)  # checks state: paused, banned, default

                updated_state_topic_ids.append(topic_id)

                # save topic url in dialog variable
                nb_client.update_dialog_variable(
                    dialog_id,
                    name=TOPIC_URL,
                    value=tg_topic.get_url())

            for dialog_message in new_dialog_messages:

                tg_message = TelegramMessage.create_from(dialog_message)

                if tg_message:

                    if topic_id not in updated_keyboard_topic_ids:

                        keyboard = tg_topic.get("reply_keyboard")

                        res = TelegramBot.send(
                            tg_message,
                            tg_topic,
                            reply_keyboard=keyboard)

                        # save topic url in dialog variable
                        nb_client.update_dialog_variable(
                            dialog_id,
                            name=TOPIC_URL,
                            value=tg_topic.get_url())

                        updated_keyboard_topic_ids.append(topic_id)

                    else:
                        res = TelegramBot.send(
                            tg_message,
                            tg_topic
                        )

                    if res is not None:
                        handled_message_counter += 1

                # save last_message for dialog_id
                dialogs.update_dialog_obj(
                    dialog_id,
                    message=dialog_message
                )
                nb_client.set_agent_variable(
                    DIALOGS_VAR_NAME,
                    dialogs.get_dialogs()
                )


            nb_client.update_agent_variable(
                STATE_VAR_NAME, {
                    "last_message": {
                        "created": now(),
                        "message": message }})

        if handled_message_counter > 0:

            nb_client.update_agent_variable(
                STATE_VAR_NAME, {
                    "empty_iterations_counter": 0
            })

            # run next iteration of checking if any new_dialogs
            nb_client.enable_delay_in_scenario_id(
                Config.get_checking_scenario_id(),
                False)
            NextBotWebhook.run_next_iteration()

            nb_client.update_agent_variable(
                STATUS_VAR_NAME, {
                    "updated": now()})


            state_mes = "Run next iteration."

        else:

            empty_iterations_qnty = (get_agent_var(STATE_VAR_NAME).get("empty_iterations_counter") or 0) + 1

            nb_client.update_agent_variable(
                STATE_VAR_NAME, {
                    "empty_iterations_counter": empty_iterations_qnty
                })

            if empty_iterations_qnty > Config.get_max_empty_iterations():

                nb_client.update_agent_variable(
                    STATE_VAR_NAME, {
                        "empty_iterations_counter": 0
                    })
                # stops checking
                nb_client.update_agent_variable(
                    STATUS_VAR_NAME, {
                        "running": False })

                nb_client.enable_trigger_scenarios()
                nb_client.enable_delay_in_scenario_id(
                    Config.get_checking_scenario_id(),
                    False)
                nb_client.clean_main_dialog()
                state_mes = "Stop checking. Enable triggers scenarios"

            else:

                nb_client.enable_delay_in_scenario_id(
                    Config.get_checking_scenario_id(),
                    True)
                # run next iteration of checking if any new_dialogs
                NextBotWebhook.run_next_iteration()
                # variables.update({STATUS_VAR_NAME: update_status_var()})
                nb_client.update_agent_variable(
                    STATUS_VAR_NAME, {
                        "updated": now()})
                state_mes = "Run next iteration."

        nb_client.update_agent_variable(
            STATE_VAR_NAME, { "auth_tokens" : nb_client.get_tokens()}
        )

        nb_client.update_agent_variable(
            STATE_VAR_NAME, {
                "auto_restart_counter": 0})

        tool_res_message = f"{handled_message_counter} messages handled" if handled_message_counter else "No messages handled"

    else:
        tool_res_message = f"Stop checking due to status"
        state_mes = f"Status {status}"

    result = (ResultBuilder()
              .silent(True)
              .tool_result(f"\nSuccess.\n{tool_res_message}\n{state_mes}")
              .build())

# при рассылке Телеграм не успевает обрабатывать запросы
# при сообщении Too many request - оставляем обработку не обработанных сообщений на следующую итерацию
except TooManyRequestsException as e:
    log_err(f"[IGNORED] {e}")

    # runs next iteration
    nb_client.enable_delay_in_scenario_id(
        Config.get_checking_scenario_id(),
        True)
    nb_client.update_agent_variable(
        STATUS_VAR_NAME, {
            "updated": now()})
    NextBotWebhook.run_next_iteration()


    result = (ResultBuilder()
              .silent(True)
              .tool_result("Too many request. Run next iteration.")
              .build())

except Exception as e:

    log_err(
        f"{e}"
        f"{traceback.format_exc()}"
    )

    auto_restart_counter = get_agent_var(STATE_VAR_NAME).get("auto_restart_counter")

    try:

        if auto_restart_counter < Config.get_max_auto_restart_qnty():

            nb_client.enable_trigger_scenarios(False)

            nb_client.update_agent_variable(
                STATUS_VAR_NAME, {
                    "running": False
                }
            )

            nb_client.enable_delay_in_scenario_id(
                Config.get_restart_scenario_id())

            nb_client.update_agent_variable(
                STATE_VAR_NAME,{
                "auto_restart_counter": auto_restart_counter + 1
                })

            NextBotWebhook.restart_app()

            ProjectBot.send_error(f"Auto Restart ({auto_restart_counter + 1})")

            result = (ResultBuilder(True)
                        .silent(True)
                        .tool_result(f"\nException.\n{e}\n"
                                     f"Auto restart (counter: {auto_restart_counter + 1}).")
                        .variables(variables)
                        .build())

        else:
            # stops checking
            variables.update({STATUS_VAR_NAME: stop_checking()})

            ProjectBot.send_error(debug_logs[-4000:])
            try:
                AdminBot.send_report("Синхронизация остановлена.",keyboard=NON_ACTIVE_STATE_KEYBOARD, timeout=5, retry_attempts=1)
            except Exception as exc:
                log_err(f"[IGNORED] `{exc}`")

            nb_client.enable_delay_in_scenario_id(
                Config.get_restart_scenario_id(),
                False
            )

            nb_client.update_agent_variable(
                STATE_VAR_NAME,{
                "auto_restart_counter": 0
                })

            result = (ResultBuilder(True)
                        .silent(True)
                        .tool_result(f"\nException.\n{e}\n"
                                     f"Stop synchronization")
                        .variables(variables)
                        .build())

    except Exception as exc:
        try:
            ProjectBot.send_error(f"Exception while exception handling.\n"
                                  f"Need manual restart\n" + debug_logs[-4000:])
        except Exception as e:
            log_err(f"[IGNORED] Can't send message to telegram {e}")

        result = (ResultBuilder(True)
                  .silent(True)
                  .tool_result(f"\nException while exception handling.\n{exc}\n")
                  .variables(variables)
                  .build())

log(f"[FINISH] `{FUNC_NAME}`")
