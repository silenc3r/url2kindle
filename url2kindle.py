import argparse
import configparser
import hashlib
import logging
import logging.config
import logging.handlers
import multiprocessing
import os
import pathlib
import re
import sys
import time

import requests

__VERSION__ = "0.8"

DEBUG = os.getenv("U2K_DEBUG")

CONFIG_FILE = os.path.join(
    os.getenv("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")),
    "url2kindle",
    "config",
)
DATA_DIR = os.path.join(
    os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local/share")),
    "url2kindle",
)
CACHE_DIR = os.path.join(
    os.getenv("XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache")),
    "url2kindle",
)
SERVICE_URL = "https://pushtokindle.fivefilters.org/send.php"
DEFAULT_SENDER = "kindle@fivefilters.org"

KINDLE_REGEX = re.compile(r"[^@]+@kindle.com$")
EMAIL_REGEX = re.compile(r"[^@]+@[^@]+\.[^@]+")


class Logger:
    """
    Logger class.
    """

    FORMAT = "[%(levelname)-s] %(name)s %(asctime)s %(message)s"
    DATE = "%Y-%m-%d %H:%M:%S"
    __log = None
    APP = "url2kindle"
    LOG_FILE = os.path.join(CACHE_DIR, "u2k.log")

    @staticmethod
    def get_default():
        """
        Return default instance of Logger
        @return Logger
        """
        if Logger.__log is None:
            if not os.path.isdir(CACHE_DIR):
                os.makedirs(CACHE_DIR)

            logger = logging.getLogger(Logger.APP)

            fh = logging.handlers.RotatingFileHandler(
                Logger.LOG_FILE, maxBytes=1048576, backupCount=3
            )
            fh.setLevel(logging.DEBUG if DEBUG else logging.INFO)
            verbose_formatter = logging.Formatter(Logger.FORMAT, Logger.DATE)
            fh.setFormatter(verbose_formatter)
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG if DEBUG else logging.WARNING)
            simple_formatter = logging.Formatter("%(message)s")
            ch.setFormatter(simple_formatter)
            logger.addHandler(fh)
            logger.addHandler(ch)
            logger.setLevel(logging.DEBUG)

            Logger.__log = logging.getLogger(Logger.APP)
        return Logger.__log

    @staticmethod
    def warning(msg, *args):
        Logger.get_default().warning(msg, *args)

    @staticmethod
    def debug(msg, *args):
        if DEBUG:
            Logger.get_default().debug(msg, *args)

    @staticmethod
    def info(msg, *args):
        Logger.get_default().info(msg, *args)

    @staticmethod
    def error(msg, *args):
        Logger.get_default().error(msg, *args)


logger = Logger()


class ConfigError(Exception):
    pass


class TooManyTries(Exception):
    pass


class URLError(Exception):
    pass


def read_config():
    """Read configuration file.

    :returns: (email, send_from) tuple or None
    :raises: ConfigError
    """
    if not os.path.isfile(CONFIG_FILE):
        return None

    with open(CONFIG_FILE, mode="r") as f:
        config = configparser.ConfigParser(default_section="url2kindle")
        config.read_file(f)

    try:
        email = config.get("url2kindle", "email")
    except configparser.Error as e:
        raise ConfigError("Kindle email address not found in configuration file") from e

    send_from = config.get("url2kindle", "from", fallback=None)

    return (email, send_from)


def save_config(email, send_from=None):
    """Create new config file.

    :email: Kindle email address
    :send_from: `send from` email address
    """
    conf_dir = os.path.dirname(CONFIG_FILE)
    if not os.path.exists(conf_dir):
        os.makedirs(conf_dir)

    config = configparser.ConfigParser(default_section="url2kindle")
    config["url2kindle"] = {"email": email}
    if send_from:
        config["url2kindle"]["from"] = send_from

    with open(CONFIG_FILE, mode="w") as f:
        config.write(f)
        logger.info(
            "Saved config file: '%s' with email:'%s', from:'%s'",
            CONFIG_FILE,
            email,
            send_from,
        )


def validate_config(cfg):
    email, send_from = cfg
    if not KINDLE_REGEX.fullmatch(email):
        raise ConfigError(f"Invalid Kindle email address: {email}")
    if not EMAIL_REGEX.fullmatch(send_from):
        logger.warning(
            "Invalid 'from' email address: %s\nFalling back to default: %s",
            send_from,
            DEFAULT_SENDER,
        )
        send_from = DEFAULT_SENDER

    return email, send_from


def send(url, email, send_from, title):
    """Send URL to Kindle."""

    # pylint: disable=line-too-long
    # headers = {"User-Agent": "url2kindle https://github.com/silenc3r/url2kindle"}
    headers = {
        "user-agent": "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:85.0) Gecko/20100101 Firefox/85.0",
        "host": "pushtokindle.fivefilters.org",
        "origin": "https://pushtokindle.fivefilters.org",
        "referer": "https://www.fivefilters.org/push-to-kindle/",
    }
    request_url = SERVICE_URL + "?context=send" + "&url=" + url
    payload = {"email": email, "from": send_from, "title": title}

    logger.info(
        "Sending url:'%s', email:'%s', from:'%s', title:'%s'",
        url,
        email,
        send_from,
        title,
    )
    r = requests.post(request_url, data=payload, headers=headers)

    if "X-PushToKindle-Failed" in r.headers:
        error_code = r.headers["X-PushToKindle-Failed"]
        if error_code == "1":
            raise URLError("Invalid email address")
        if error_code == "2":
            raise URLError("404 - URL not found!")
        error_msg = f"X-PushToKindle-Failed: {error_code}" + "\n" + r.text
        raise URLError(error_msg)
    if r.content == b"Invalid URL supplied":
        raise URLError(r.content.decode("utf-8"))


def send_or_save(url, email, send_from="", title=""):
    try:
        send(url, email, send_from, title)
    except requests.exceptions.RequestException:
        logger.warning("Network error. Saving url for resend later: '%s'", url)
        url_hash = hashlib.blake2s(url.encode()).hexdigest()
        filename = pathlib.Path(DATA_DIR, url_hash)
        with open(filename, "w") as f:
            f.write(url)
            f.write(email)
            f.write(send_from)
            f.write(title)
        raise


def _retry_sending(filename):
    if os.fork() != 0:
        return

    with open(filename, "r") as f:
        text = f.readlines()
        url = text[0].rstrip()
        email = text[1].rstrip()
        send_from = text[2].rstrip()
        title = text[3].rstrip()

    try:
        logger.info(
            "Retrying sending url:'%s' email:'%s' from:'%s' title:'%s'",
            url,
            email,
            send_from,
            title,
        )
        send(url, email, send_from, title)
    except URLError:
        logger.info("Failed to resend - wrong url: '%s'", url)
        filename.unlink()
    except requests.exceptions.RequestException:
        pass


def retry_saved():
    """
    Retry sending failed requests.
    Skip requests sent in the last 5 minutes.
    Uses lock file to prevent races.
    """
    now = time.time()
    lockfile = pathlib.Path(DATA_DIR, "LOCK")
    if lockfile.exists():
        if (now - lockfile.stat().st_mtime) < 600:
            logger.debug("Lockfile recently created, aborting")
            return
        lockfile.unlink()

    logger.debug("Creating lockfile")
    lockfile.touch(exist_ok=True)
    files = filter(lambda p: not p.match("LOCK"), pathlib.Path(DATA_DIR).glob("*"))
    five_mins_ago = now - 300
    one_month_ago = now - 60 * 60 * 24 * 30
    procs = []
    for filename in files:
        mod_time = filename.stat().st_mtime
        if mod_time < one_month_ago:
            logger.debug("Skipping retrying, file too old: %s", filename)
            filename.unlink()
            continue
        if mod_time > five_mins_ago:
            logger.debug("Skipping retrying, file recently created: %s", filename)
            continue
        p = multiprocessing.Process(target=_retry_sending, args=(filename,))
        procs.append(p)
        p.start()

    for p in procs:
        p.join()


def get_parser():
    parser = argparse.ArgumentParser(
        prog="u2k", description="Send web articles to Kindle from cli."
    )
    parser.add_argument(
        "--version", action="version", version=f"url2kindle {__VERSION__}"
    )
    parser.add_argument("url", help="URL to send")
    parser.add_argument(
        "-t", "--title", metavar="TITLE", help="set custom title for article"
    )
    return parser


def prompt_for_credentials():
    email, send_from = "", ""
    tries = 3
    while tries > 0:
        email = input("Kindle email: ").strip()
        if KINDLE_REGEX.fullmatch(email):
            break
        print(f"Invalid Kindle email address: {email}", file=sys.stderr)
        email = ""
        tries -= 1
    if email == "":
        raise TooManyTries

    tries = 3
    while tries > 0:
        send_from = input("Send from: ").strip()
        if EMAIL_REGEX.fullmatch(send_from):
            break
        print(f"Invalid 'from' email address: {send_from}", file=sys.stderr)
        send_from = ""
        tries -= 1
    if send_from == "":
        print(f"Too many tries. Using default: {DEFAULT_SENDER}")
        send_from = DEFAULT_SENDER

    return email, send_from


def _fix_send_from_bug(sender):
    if sender != DEFAULT_SENDER:
        logger.warning(
            "Custom 'from' addresses are currently bugged, falling back to default: '%s'",
            DEFAULT_SENDER,
        )
    return DEFAULT_SENDER


def main():
    parser = get_parser()
    args = parser.parse_args()

    url = args.url
    title = args.title or ""

    try:
        config = read_config()
    except ConfigError as e:
        logger.error(e)
        return 1

    if config:
        email, send_from = validate_config(config)
        logger.debug("Config: email:'%s', from:'%s'", email, send_from)
    else:
        try:
            email, send_from = prompt_for_credentials()
        except KeyboardInterrupt:
            return 1
        except TooManyTries:
            logger.error("Too many tries")
            return 1

        save_config(email, send_from)

    send_from = _fix_send_from_bug(send_from)

    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR)

    try:
        send_or_save(url, email, send_from, title)
    except KeyboardInterrupt:
        return 1
    except URLError as e:
        logger.error(e)
        return 1

    retry_saved()
    return 0


if __name__ == "__main__":
    sys.exit(main())
