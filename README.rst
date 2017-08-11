
Introduction
============

.. image :: https://badges.gitter.im/adafruit/circuitpython.svg
    :target: https://gitter.im/adafruit/circuitpython?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge
    :alt: Gitter

.. image :: https://img.shields.io/discord/327254708534116352.svg
    :target: https://adafru.it/discord
    :alt: Discord

Rosie is an on-microcontroller testing service that runs on a Raspberry Pi. Its
meant to run after Travis builds and tests binaries. Build artifacts and test
results are stored to an Amazon S3 bucket. It is used to test
`Adafruit CircuitPython <https://github.com/adafruit/circuitpython>`_.

Setup
=======

Here are the instructions for one time setup. Its simpler to start once
everything is installed.

Debian Dependencies
+++++++++++++++++++++++++++

.. code-block:: shell

    sudo apt-get update # make sure you have the latest packages
    sudo apt-get upgrade # make sure already installed packages are latest
    sudo apt-get install git python3 python3-venv python3-pip redis-server libffi-dev libssl-dev pmount screen

ngrok
+++++++

Rosie CI also uses `ngrok <>`_ installed manually to present the http interface
to the outside internet. This is preferable to configuring your router to expose
your Raspberry Pi directly. See `here <https://ngrok.com/download>`_ for
installation instructions and `here <https://dashboard.ngrok.com/get-started>`_
for instructions on authenticating your instance. Without a paid plan, your url
will change every time you run ngrok. It will still work for testing but be
inconvenient when connecting multiple GitHub repos to it.

Rosie CI
++++++++++

Once the dependencies are installed, now clone the git repo into your home directory.

.. code-block:: shell

    git clone https://github.com/adafruit/rosie-ci.git
    cd rosie-ci

.. seealso:: You may want to `set up a credential helper <https://help.github.com/articles/caching-your-github-password-in-git/>`_.

First, set up a virtual environment and install the deps. (This is Raspberry Pi
specific. Debian has done some weird things around pip.)

.. code-block:: shell

  python3 -m venv .env
  source .env/bin/activate
  pip install -r requirements.txt

Secrets!
+++++++++

Rosie needs a few secrets to do its work. Never, ever check these into source
control!

They are stored as environment variables in ``env.sh``.

So, copy the example ``env.sh`` and edit it.

.. code-block:: shell

    cp env-template.sh env.sh
    nano env.sh

Do CTRL-X to exit and press Y to save the file before exiting.

Rosie configuration
+++++++++++++++++++

Rosie has additional configuration necessary before she can start testing.

First, we'll do like did for secrets and copy the template to the correct place
and then edit it.

.. code-block:: shell

    cp rosie-template.yml .rosie.yml
    nano .rosie.yml

To determine the USB paths of connected devices use ``/dev/disk/by-path`` or
``/dev/serial/by-path`` to list the active devices before plugging the device in
and then rerun it after plugging in the new board.

Test repo configuration
+++++++++++++++++++++++++++

For now, Rosie only supports testing new CircuitPython builds. Setting that up
is pretty simple.

First, there is a ``.rosie.yml`` file in the CircuitPython repo that tells Rosie
where to find binaries built by Travis and where to find the tests. It also
includes test configuration things such as helper modules that need to be loaded
alongside the test and how to evaluate the results.

Next, you need to hook the GitHub repo to Rosie via a webhook with the rosie URL
such as ``https://<subdomain>.ngrok.io/github``. It should have the Create, Pull
Request, Push and Release events checked. Set the secret as the same as from
your ``env.sh`` file on the Raspberry Pi.

Lastly, Travis needs to be setup to call Rosie to let it know its progress. This
is done through ``.travis.yml``. Its added as a ``webhooks`` under
``notifications``.

.. code-block:: yaml

    webhooks:
      urls:
        - https://<subdomain>.ngrok.io/travis
      on_success: always
      on_failure: always
      on_start: always
      on_cancel: always
      on_error: always

Once the webhooks are setup, the next push should trigger Rosie. After Travis
notifies Rosie that its started, Rosie will attach a status to the commit on
GitHub. After it finishes, the status will include a link to the test log.

Usage Example
=============

To run Rosie we'll use screen to manage all of the individual pieces. Luckily,
we have a screenrc file that manages starting everything up.

.. code-block:: shell

    screen -c rosie-ci.screenrc

This command will return back to your prompt with something like
``[detached from 10866.pts-0.raspberrypi]``. This means that Rosie is now running
within screen session behind the scenes. You can view output of it by attaching
to the screen with:

.. code-block:: shell

    screen -r

Once reattached you can stop everything by CTRL-Cing repeatedly or detach again
with CTRL-A then D. If any errors occur, a sleep command will be run so you can
view the output before screen shuts down.

How it works
============

Rosie uses Flask to accept webhooks from GitHub and Celery. The GitHub webhook
triggers a fetch of the commit data. The first "starting" Travis webhook simply
triggers Rosie to notify GitHub that it intends on testing the commit. Rosie then
waits until Travis finishes because it relies on build artifacts that Travis
creates. This approach ensures a consistent build environment for binaries (and
Debian on Raspberry Pi has old ARM GCC packages).

Celery is backed by Redis for scheduling and communication. Redis is also used
for temporary logs and locking resources such as repos and boards.

Contributing
============

Contributions are welcome! Please read our `Code of Conduct
<https://github.com/adafruit/rosie-ci/blob/master/CODE_OF_CONDUCT.md>`_
before contributing to help this project stay welcoming.

API Reference
=============

.. toctree::
   :maxdepth: 2

   api
