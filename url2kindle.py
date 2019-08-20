import argparse
import configparser
import hashlib
import multiprocessing
import os
import pathlib
import sys
import time
import urllib
from urllib import parse, request

__VERSION__ = "0.5"

CONFIG_FILE = os.path.join(
    os.getenv("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")),
    "url2kindle",
    "config",
)
DATA_DIR = os.path.join(
    os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local/share")),
    "url2kindle",
)
DOMAINS = {
    "free.kindle.com": 1,
    "kindle.com": 2,
    "iduokan.com": 3,
    "kindle.cn": 4,
    "pbsync.com": 5,
}
SERVICE_URL = "https://pushtokindle.fivefilters.org/send.php"

# fmt: off
class ConfigError(Exception): pass  # noqa: E302, E701
class UnknownError(Exception): pass  # noqa: E302, E701
class URLError(Exception): pass  # noqa: E302, E701
# fmt: on


def read_config():
    """Read configuration file.

    :returns: (name, domain, send_from) tuple or None
    :raises: ConfigError
    """
    if not os.path.isfile(CONFIG_FILE):
        return None

    with open(CONFIG_FILE, mode="r") as f:
        config = configparser.ConfigParser(default_section="url2kindle")
        config.read_file(f)

    try:
        email = config.get("url2kindle", "email")
    except configparser.Error:
        raise ConfigError("No email address found in configuration file")

    try:
        name, domain = email.split("@")
        domain_number = DOMAINS[domain]
    except (KeyError, ValueError):
        raise ConfigError(f"Invalid Kindle email address '{email}'")

    send_from = config.get("url2kindle", "from", fallback=None)

    return (name, domain_number, send_from)


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


def _prepare_payload(url, name, domain_number, send_from=None, title=None):
    assert domain_number in range(1, 6)

    send_from = send_from or ""
    title = title or ""

    # original Firefox addon includes context and url parameters in
    # request url, but we'll put them in payload
    payload = parse.urlencode(
        {
            "context": "send",
            "email": name,
            "domain": domain_number,
            "from": send_from,
            "title": title,
            "url": url,
        }
    ).encode()
    return payload


def send(payload):
    """Send URL to Kindle.

    :payload: data to send

    :raises: UnknownError, URLError, urllib.error.URLError
    """
    headers = {"User-Agent": "url2kindle https://github.com/silenc3r/url2kindle"}

    req = request.Request(SERVICE_URL, data=payload, headers=headers)
    resp = request.urlopen(req)
    error_code = resp.getheader("X-PushToKindle-Failed")
    if error_code == "2":
        raise URLError("404 - URL not found!")
    elif error_code:
        raise UnknownError(error_code)


def send_or_save(url, name, domain_number, send_from=None, title=None):
    url_hash = hashlib.blake2s(url.encode()).hexdigest()
    filename = pathlib.Path(DATA_DIR, url_hash)
    if filename.exists():
        filename.unlink()

    payload = _prepare_payload(url, name, domain_number, send_from, title)
    try:
        send(payload)
    except (urllib.error.URLError, UnknownError):
        payload_str = payload.decode("utf-8")
        with open(filename, "w") as f:
            f.write(payload_str)
        raise


def _retry_sending(filename):
    if os.fork() != 0:
        return

    with open(filename, "r") as f:
        payload_str = f.read().rstrip()

    payload = payload_str.encode()
    try:
        send(payload)
        filename.unlink()
    except URLError:
        filename.unlink()
    except urllib.error.URLError:
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
            return
        else:
            lockfile.unlink()

    lockfile.touch(exist_ok=True)
    five_mins_ago = now - 300
    one_month_ago = now - 60 * 60 * 24 * 30
    files = []
    for filename in pathlib.Path(DATA_DIR).glob("*"):
        mod_time = filename.stat().st_mtime
        if mod_time < one_month_ago:
            filename.unlink()
        elif mod_time < five_mins_ago:
            files.append(filename)

    # lockfile.unlink()

    procs = []
    for filename in files:
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
    parser.add_argument("url", nargs=1, help="URL to send")
    parser.add_argument(
        "-t", "--title", metavar="TITLE", help="set custom title for article"
    )
    return parser


def main():
    def err(*args):
        print("ERROR:", *args, file=sys.stderr)

    parser = get_parser()
    args = parser.parse_args()

    url = args.url
    title = args.title

    try:
        config = read_config()
    except ConfigError as e:
        err(e)
        return 2

    if config:
        name, dnumber, send_from = config
    else:
        try:
            email = input("Kindle email: ")
        except KeyboardInterrupt:
            return 1

        if "@" not in email:
            err("Invalid email address!")
            return 1
        name, domain = email.split("@")
        if domain not in DOMAINS:
            domain_list_str = ", ".join("@" + d for d in DOMAINS)
            err("Email domain must be one of:", domain_list_str)
            return 1
        dnumber = DOMAINS[domain]

        default_send_from = "kindle@fivefilters.org"
        try:
            send_from = input(f"Send from (default: {default_send_from}): ")
        except KeyboardInterrupt:
            return 1

        send_from = send_from.strip() or default_send_from
        save_config(email, send_from)
        print("Created config file '{}'".format(CONFIG_FILE))

    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR)

    return_code = 0
    try:
        send_or_save(url, name, dnumber, send_from, title)
    except KeyboardInterrupt:
        return 1
    except URLError as e:
        err(e)
        return_code = 1
    except UnknownError as e:
        err("[{}]".format(e), "Something went wrong...")
        return_code = 1
    except urllib.error.URLError as e:
        err(e.args[0])
        return_code = 1

    retry_saved()

    return return_code


if __name__ == "__main__":
    main()
