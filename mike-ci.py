# The MIT License (MIT)
#
# Copyright (c) 2017 Scott Shawcroft for Adafruit Industries
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from flask import Flask
from flask import jsonify
from flask import request
from flask import abort
from flask import json

from tasks import make_celery

app = Flask(__name__)
app.config.update(
    CELERY_BROKER_URL='amqp://localhost:5672/',
    CELERY_RESULT_BACKEND='rpc://localhost:5672/'
)
celery = make_celery(app)

@celery.task()
def add_together(a, b):
    return a + b

import base64
import hmac
import hashlib
import binascii
import os
import queue

import requests

from OpenSSL.crypto import verify, load_publickey, FILETYPE_PEM, X509
from OpenSSL.crypto import Error as SignatureError

github_webhook_secret = None
if "GITHUB_WEBHOOK_SECRET" not in os.environ:
    github_webhook_secret = binascii.unhexlify(os.environ["GITHUB_WEBHOOK_SECRET"])

@celery.task()
def load_repo(owner, repo):
    pass

#Compare the HMAC hash signature
def verify_hmac_hash(data, signature):
    if not github_webhook_secret:
        return False
    mac = hmac.new(github_webhook_secret, msg=data, digestmod=hashlib.sha1)
    return hmac.compare_digest('sha1=' + mac.hexdigest(), signature)

@app.route("/github", methods=['POST'])
def github():
    signature = request.headers.get('X-Hub-Signature')
    data = request.data
    if verify_hmac_hash(data, signature):
        abort(401)

    if request.headers.get('X-GitHub-Event') == "ping":
        return jsonify({'msg': 'Ok'})

    print(request.json)
    return jsonify({'msg': 'Ok'})

# Adapted from: https://gist.github.com/andrewgross/8ba32af80ecccb894b82774782e7dcd4
def check_authorized(signature, public_key, payload):
    """
    Convert the PEM encoded public key to a format palatable for pyOpenSSL,
    then verify the signature
    """
    pkey_public_key = load_publickey(FILETYPE_PEM, public_key)
    certificate = X509()
    certificate.set_pubkey(pkey_public_key)
    verify(certificate, signature, payload, str('sha1'))

def _get_travis_public_key():
    response = requests.get("https://api.travis-ci.org/config", timeout=10.0)
    response.raise_for_status()
    return response.json()['config']['notifications']['webhook']['public_key']

@app.route("/travis", methods=['POST'])
def travis():
    signature = base64.b64decode(request.headers.get('Signature'))
    try:
        public_key = _get_travis_public_key()
    except requests.Timeout:
        print("Timed out when attempting to retrieve Travis CI public key")
        abort(500)
    except requests.RequestException as e:
        print("Failed to retrieve Travis CI public key")
        abort(500)
    try:
        check_authorized(signature, public_key, request.form["payload"])
    except SignatureError:
        abort(401)
    data = json.loads(request.form["payload"])

    print(data["branch"])

    if data["status"] in ("started", ):
        print("travis started")
        report_start(data)
    elif data["status"] in ("passed", ):
        print("travis finished")
        try:
            testing_queue.put(data, block=False)
        except queue.Full:
            report_error(owner, repo, sha, "Testing queue full.")
    elif data["status"] is None:
        print("travis None")
        print(data)
    else:
        print("unhandled status:", data["status"])
    return jsonify({'status': 'received'})
