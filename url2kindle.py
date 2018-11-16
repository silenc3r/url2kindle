import configparser
import os
import sys

from urllib import parse, request

__VERSION__ = '0.3'

CONFIG_FILE = os.path.join(
    os.getenv('XDG_CONFIG_HOME',
              os.path.join(os.path.expanduser('~'), '.config')),
    'url2kindle', 'config'
)
DOMAINS = {
    'free.kindle.com': 1,
    'kindle.com': 2,
    'iduokan.com': 3,
    'kindle.cn': 4,
    'pbsync.com': 5,
}


class ConfigError(Exception): pass  # noqa: E302, E701
class UnknownError(Exception): pass  # noqa: E302, E701
class URLError(Exception): pass  # noqa: E302, E701


def read_config():
    """Read configuration file.

    :returns: name, domain tuple
    :raises: ConfigError
    """
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, mode='r') as f:
            config = configparser.ConfigParser(default_section='url2kindle')
            config.read_file(f)
        try:
            email = config.get('url2kindle', 'email')
            name, domain = email.split('@')
            if domain not in DOMAINS:
                raise ValueError
        except (configparser.Error, ValueError):
            raise ConfigError

        return (name, domain)


def write_config(email):
    """Create new config file.

    :email: User's Kindle email address
    """
    conf_dir = os.path.dirname(CONFIG_FILE)
    if not os.path.exists(conf_dir):
        os.makedirs(conf_dir)
    config = configparser.ConfigParser(default_section='url2kindle')
    config['url2kindle'] = {'email': email}
    with open(CONFIG_FILE, mode='w') as f:
        config.write(f)


def send(url, name, domain_number):
    """Send URL to Kindle.

    :url: URL of website to send
    :name: local-part of email address
    :domain_number: numeric value representing domain of email address

    :raises: UnknownError, URLError
    """
    assert domain_number in range(1, 6)

    service_url = 'https://pushtokindle.fivefilters.org/send.php'
    headers = {'User-Agent': 'url2kindle https://github.com/silenc3r/url2kindle'}
    data = parse.urlencode({
        'context': 'send',
        'email': name,
        'domain': domain_number,
        'url': url,
    }).encode()

    req = request.Request(service_url, data=data, headers=headers)
    resp = request.urlopen(req)
    error_code = resp.getheader('X-PushToKindle-Failed')
    if error_code == '2':
        raise URLError
    elif error_code:
        raise UnknownError(error_code)


def main():
    def fail(*args, code=1):
        print(*args, file=sys.stderr)
        sys.exit(code)

    if len(sys.argv) != 2:
        fail("usage: u2k URL")

    if sys.argv[1] in ["-v", "--version"]:
        print("url2kindle, version {}".format(__VERSION__))
        sys.exit(0)

    try:
        config = read_config()
    except ConfigError:
        fail("Error: Config file is corrupted!", code=2)

    if config:
        name, domain = config
    else:
        try:
            email = input("Kindle email: ")
            if '@' not in email:
                fail("Error: Invalid email address!")
            name, domain = email.split('@')
            if domain not in DOMAINS:
                domain_list_str = ', '.join('@' + d for d in DOMAINS)
                fail("Error: Email domain must be one of:", domain_list_str)
        except KeyboardInterrupt:
            fail()

        write_config(email)
        print("Created config file: {}".format(CONFIG_FILE))

    url = sys.argv[1]
    dnumber = DOMAINS[domain]
    try:
        send(url, name, dnumber)
    except URLError:
        fail("Error: 404 URL not found!")
    except UnknownError as e:
        fail("Error:", "[{}]".format(e), "Something went wrong...")
    except KeyboardInterrupt:
        fail()


if __name__ == "__main__":
    main()
