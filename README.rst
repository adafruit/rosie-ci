
Introduction
============

.. image :: https://badges.gitter.im/adafruit/circuitpython.svg
    :target: https://gitter.im/adafruit/circuitpython?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge
    :alt: Gitter

Mike is an on-microcontroller testing service that runs on a Raspberry Pi. Its
meant to run after Travis builds and tests binaries. Build artifacts and test
results are stored to an Amazon S3 bucket. It is used to test
`Adafruit CircuitPython <https://github.com/adafruit/circuitpython>`_.

Setup
=======

On raspbian:

.. code-block:: shell

  sudo apt-get update # make sure you have the latest packages
  sudo apt-get upgrade # make sure already installed packages are latest
  sudo apt-get install git python3 python3-pip redis-server

First, set up a virtual environment and install the deps. (This is Raspberry Pi
specific. Debian has done some weird things around pip.)

.. code-block:: shell

  python3 -m venv .env --without-pip --system-site-packages
  source .env/bin/activate
  python3 -m pip install -r requirements.txt

Usage Example
=============

To run Mike do:

.. code-block:: shell

  ./start.sh

How it works
============

Mike uses Flask to accept webhooks from GitHub and Celery. The GitHub webhook
triggers a fetch of the commit data. The first "starting" Travis webhook simply
triggers Mike to notify GitHub that it intends on testing the commit. Mike waits
until Travis finishes because it relies on build artifacts that Travis creates.
This approach ensures a consistent build environment for binaries (and Debian on
Raspberry Pi has old ARM GCC packages).

Celery is backed by Redis for scheduling and communication. Redis is also used
for temporary logs and locking resources such as repos and boards.

Contributing
============

Contributions are welcome! Please read our `Code of Conduct
<https://github.com/adafruit/Adafruit_CircuitPython_mike-ci/blob/master/CODE_OF_CONDUCT.md>`_
before contributing to help this project stay welcoming.

API Reference
=============

.. toctree::
   :maxdepth: 2

   api