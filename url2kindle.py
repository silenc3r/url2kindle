import configparser
import os
import sys

from urllib import parse, request

__VERSION__ = "0.4"

CONFIG_FILE = os.path.join(
    os.getenv("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")),
    "url2kindle",
    "config",
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


def write_config(email, send_from=None):
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


def send(url, name, domain_number, send_from=None, title=None):
    """Send URL to Kindle.

    :url: URL of website to send
    :name: local-part of email address
    :domain_number: numeric value representing domain of email address
    :send_from: `send from` email address
    :title: custom title

    :raises: UnknownError, URLError
    """
    assert domain_number in range(1, 6)

    send_from = send_from or ""
    title = title or ""

    # original Firefox addon includes context and url parameters in
    # request url, but we'll put them in data
    data = parse.urlencode(
        {
            "context": "send",
            "email": name,
            "domain": domain_number,
            "from": send_from,
            "title": title,
            "url": url,
        }
    ).encode()
    headers = {"User-Agent": "url2kindle https://github.com/silenc3r/url2kindle"}

    req = request.Request(SERVICE_URL, data=data, headers=headers)
    resp = request.urlopen(req)
    error_code = resp.getheader("X-PushToKindle-Failed")
    if error_code == "2":
        raise URLError("404 - URL not found!")
    elif error_code:
        raise UnknownError(error_code)


def main():
    def fail(*args, code=1):
        if args:
            print("ERROR:", *args, file=sys.stderr)
        sys.exit(code)

    if len(sys.argv) != 2:
        print("usage: u2k URL", file=sys.stderr)

    if sys.argv[1] in ["-v", "--version"]:
        print("url2kindle, version {}".format(__VERSION__))
        sys.exit(0)

    url = sys.argv[1]

    # TODO: use Argparser to get title
    title = None

    try:
        config = read_config()
    except ConfigError as e:
        fail(str(e), code=2)

    if config:
        name, dnumber, send_from = config
    else:
        try:
            email = input("Kindle email: ")
        except KeyboardInterrupt:
            sys.exit(1)

        if "@" not in email:
            fail("Invalid email address!")
        name, domain = email.split("@")
        if domain not in DOMAINS:
            domain_list_str = ", ".join("@" + d for d in DOMAINS)
            fail("Email domain must be one of:", domain_list_str)
        dnumber = DOMAINS[domain]

        default_send_from = "kindle@fivefilters.org"
        try:
            send_from = input(f"Send from (default: {default_send_from}): ")
        except KeyboardInterrupt:
            sys.exit(1)

        send_from = send_from.strip() or default_send_from
        write_config(email, send_from)
        print("Created config file '{}'".format(CONFIG_FILE))

    try:
        send(url, name, dnumber, send_from, title)
    except URLError as e:
        fail(str(e))
    except UnknownError as e:
        fail("[{}]".format(e), "Something went wrong...")
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
