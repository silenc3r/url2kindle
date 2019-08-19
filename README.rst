url2kindle
==========

**url2kindle** - send web articles to your Kindle from terminal

url2kindle is (unofficial) cli interface to `Push to Kindle <http://fivefilters.org/kindle-it/>`_.


Installation
============

.. code-block:: shell

    $ pipx install url2kindle

or

.. code-block:: shell

    $ pip install url2kindle


Usage
=====

First you need to configure your Amazon accout. Detailed instructions how to do that can be found
`here <http://help.fivefilters.org/customer/portal/articles/178337-kindle-e-mail-address>`_.

To send article to Kindle run:

.. code-block:: shell

    $ u2k http://example.com/article.html

On first run ``url2kindle`` will ask for your Kindle email address and 'send from' address.
If you leave 'send from' field blank it will default to ``kindle@fivefilters.org``.
Both addresses will be saved in configuration file.