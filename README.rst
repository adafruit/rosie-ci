
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

First, set up a virtual environment and install the deps.

.. code-block:: shell

  python3 -m venv .env
  source .env/bin/activate
  pip install -r requirements.txt

Usage Example
=============

To run Mike do:

.. code-block:: shell

  ./start.sh

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
