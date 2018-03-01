import configparser
import os
import sys

from urllib import parse, request

CONFIG_FILE = os.path.join(os.getenv('XDG_CONFIG_HOME',
                                     os.path.join(os.path.expanduser('~'), '.config')),
                           'url2kindle', 'config')

DOMAINS = {
    'free.kindle.com': 1,
    'kindle.com': 2,
    'iduokan.com': 3,
    'kindle.cn': 4,
    'pbsync.com': 5,
}


class BadURL(Exception): pass
class InvalidEmailAddress(Exception): pass


def read_config():
    """Read configuration file.

    :returns: name, domain tuple
    :raises: InvalidEmailAddress
    """
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, mode='r') as f:
            config = configparser.ConfigParser(default_section='url2kindle')
            config.read_file(f)
        email = config.get('url2kindle', 'email')
        try:
            name, domain = email.split('@')
            if domain not in DOMAINS:
                raise ValueError
        except ValueError:
            raise InvalidEmailAddress

        return (name, domain)


def write_config(email):
    """Create new config file.

    :email: Users Kindle email address
    """
    conf_dir = os.path.dirname(CONFIG_FILE)
    if not os.path.exists(conf_dir):
        os.mkdir(conf_dir)
    config = configparser.ConfigParser(default_section='url2kindle')
    config['url2kindle'] = {'email': email}
    with open(CONFIG_FILE, mode='w') as f:
        config.write(f)


def send(url, name, domain_number):
    """Send URL to Kindle.

    :url: URL of website to send
    :name: local-part of email address
    :domain_number: numeric value representing domain of email address

    :raises: BadURL
    """
    assert domain_number in range(1, 6)

    service_url = 'http://fivefilters.org/kindle-it/send.php'
    headers = {'User-Agent': 'url2kindle https://github.com/silenc3r/url2kindle'}
    data = parse.urlencode({
        'context': 'send',
        'email': name,
        'domain': domain_number,
        'url': url,
    }).encode()

    req = request.Request(service_url, data=data, headers=headers)
    resp = request.urlopen(req)
    if resp.getheader('X-PushToKindle-Failed') == '2':
        raise BadURL()


def main():
    if len(sys.argv) != 2:
        print("usage: u2k URL", file=sys.stderr)
        sys.exit(1)

    try:
        config = read_config()
    except (configparser.NoOptionError, InvalidEmailAddress):
        print("Error: Config file is corrupted!", file=sys.stderr)
        sys.exit(1)

    if config is not None:
        name, domain = config
    else:
        try:
            email = input("Kindle email: ")
        except KeyboardInterrupt:
            print()
            sys.exit(1)
        if '@' not in email:
            print("Error: Invalid email address!", file=sys.stderr)
            sys.exit(1)
        name, domain = email.split('@')
        if domain not in DOMAINS:
            domain_list_str = ', '.join('@' + d for d in DOMAINS)
            print("Error: Email domain must be one of:", domain_list_str, file=sys.stderr)
            sys.exit(1)
        write_config(email)

    url = sys.argv[1]
    try:
        dnumber = DOMAINS[domain]
        send(url, name, dnumber)
    except BadURL:
        print("Error: Bad URL!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
