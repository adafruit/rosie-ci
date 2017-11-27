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

import base64
import hmac
import hashlib
import binascii
import os
import os.path
import random
import traceback
import redis
import sys

import sh
from sh import git

import requests
from OpenSSL.crypto import verify, load_publickey, FILETYPE_PEM, X509
from OpenSSL.crypto import Error as SignatureError

import yaml

from flask import Flask
from flask import jsonify
from flask import request
from flask import abort
from flask import json
from flask import Response

from werkzeug.utils import secure_filename

from tasks import make_celery

from celery import group
from kombu import Queue, Exchange

import boto3
from botocore.handlers import disable_signing

import tester

app = Flask(__name__)
app.config.update(
    CELERY_BROKER_URL='redis://localhost:6379/0',
    CELERY_RESULT_BACKEND='redis://localhost:6379/0',
    CELERY_TASK_QUEUES=(Queue('high', Exchange('high'), routing_key='high'),
                        Queue('low', Exchange('low'), routing_key='low'))
)
celery = make_celery(app)

config = {}
with open('.rosie.yml') as f:
    config = yaml.safe_load(f)

redis = redis.StrictRedis()

github_personal_access_token = None
if "GITHUB_ACCESS_TOKEN" in os.environ:
    github_personal_access_token = os.environ["GITHUB_ACCESS_TOKEN"]

anonymous_s3 = boto3.resource('s3')
anonymous_s3.meta.client.meta.events.register("choose-signer.s3.*", disable_signing)

cwd = os.getcwd()

def set_status(repo, sha, state, target_url, description):
    redis.append("log:" + repo + "/" + sha, "State %s: %s\n" % (state, description))
    if state == "error":
        print("Run {}/{} errored out: {}".format(repo, sha, description))
    if state in ["pending", "error"]:
        return
    data = {
        "state": state,
        "target_url": target_url,
        "description": description,
        "context": "rosie-ci/" + config["overall"]["node-name"]
    }
    r = requests.post("https://api.github.com/repos/" + repo + "/statuses/" + sha,
                      json=data,
                      auth=(config["overall"]["github-username"], github_personal_access_token))

def final_status(repo, sha, state, description):
    # TODO(tannewt): Upload to the public S3 bucket instead. These may disappear.
    set_status(repo, sha, state, "https://rosie-ci.ngrok.io/log/" + repo + "/" + sha, description)

@celery.task(queue="low")
def load_code(repo, ref):
    print("loading code from " + repo)
    os.chdir(cwd)

    # Look up our original repo so that we only load objects once.
    base_repo = redis.get("source:" + repo)
    if base_repo is None:
        r = requests.get("https://api.github.com/repos/" + repo,
                         auth=(config["overall"]["github-username"], github_personal_access_token))
        r = r.json()
        base_repo = "source"
        if "source" in r:
            base_repo = r["source"]["full_name"]
        redis.set("source:" + repo, base_repo)
    if base_repo is "source":
        base_repo = repo
    if type(base_repo) is bytes:
        base_repo = base_repo.decode("utf-8")

    print("Source repo of " + repo + " is " + base_repo)

    repo_path = "repos/" + base_repo
    github_base_url = "https://github.com/" + base_repo + ".git"
    github_head_url = "https://github.com/" + repo + ".git"
    print("waiting for repo lock")
    with redis.lock(base_repo, timeout=5*60, blocking_timeout=20*60):
        if not os.path.isdir(repo_path):
            os.makedirs(repo_path)
            git.clone(github_base_url, repo_path)

            # We must make .tmp after cloning because cloning will fail when the
            # directory isn't empty.
            os.makedirs(repo_path + "/.tmp")
        os.chdir(repo_path)
        git.fetch(github_head_url, ref)
    print("loaded", repo, ref)

@celery.task(queue="high")
def test_board(repo_lock_token, ref=None, repo=None, tag=None, board=None):
    base_repo = redis.get("source:" + repo).decode("utf-8")
    repo_path = cwd + "/repos/" + base_repo
    log_key = "log:" + repo + "/" + ref
    os.chdir(repo_path)
    test_config_ok = True
    test_cfg = None
    if os.path.isfile(".rosie.yml"):
        with open(".rosie.yml", "r") as f:
            test_cfg = yaml.safe_load(f)

    if not test_cfg or "binaries" not in test_cfg or not ("prebuilt_s3" in test_cfg["binaries"] or "rosie_upload" in test_cfg["binaries"]):
        redis.append(log_key, "Missing or invalid .rosie.yml in repo.\n")
        return (repo_lock_token, False, True)

    version = ref[:7]
    if tag is not None:
        version = tag
    binary = None
    if "rosie_upload" in test_cfg["binaries"]:
        fn = None
        try:
            fn = test_cfg["binaries"]["rosie_upload"]["file_pattern"].format(board=board["board"], short_sha=version, version=version, extension="uf2")
        except KeyError as e:
            redis.append(log_key, "Unable to construct filename because of unknown key: {0}\n".format(str(e)))
            return (repo_lock_token, False, True)
        except Exception as e:
            e = sys.exc_info()[0]
            redis.append(log_key, "Other error: {0}\n".format(e))
            return (repo_lock_token, False, True)
        print("finding file in redis: " + fn)
        redis_file = None
        if "*" in fn:
            keys = redis.keys("file:" + fn)
            keys.sort()
            if len(keys) > 0:
                redis_file = redis.get(keys[-1])
        else:
            redis_file = redis.get("file:" + fn)
        if redis_file:
            random_portion = '%010x' % random.randrange(16**10)
            tmp_filename = ".tmp/" + random_portion + "-" + secure_filename(fn.rsplit("/", 1)[-1])
            os.makedirs(".tmp", exist_ok=True)
            with open(tmp_filename, "wb") as f:
                f.write(redis_file)
            binary = tmp_filename
    if binary is None and "prebuilt_s3" in test_cfg["binaries"]:
        print("looking in aws")
        fn = None
        try:
            fn = test_cfg["binaries"]["prebuilt_s3"]["file_pattern"].format(board=board["board"], short_sha=version, version=version, extension="uf2")
        except KeyError as e:
            redis.append(log_key, "Unable to construct filename because of unknown key: {0}\n".format(str(e)))
            return (repo_lock_token, False, True)
        except Exception as e:
            e = sys.exc_info()[0]
            redis.append(log_key, "Other error: {0}\n".format(e))
            return (repo_lock_token, False, True)
        b = anonymous_s3.Bucket(test_cfg["binaries"]["prebuilt_s3"]["bucket"])
        prefix = fn
        suffix = None
        if "*" in prefix:
            prefix, suffix = prefix.split("*", 1)
        if suffix and "*" in suffix:
            redis.append(log_key, "Only one * supported in file_pattern")
            return (repo_lock_token, False, True)

        for obj in b.objects.filter(Prefix=prefix):
            if obj.key.endswith(suffix):
                tmp_filename = ".tmp/" + obj.key.rsplit("/", 1)[1]
                try:
                    b.download_file(obj.key, tmp_filename)
                except FileNotFoundError as e:
                    redis.append(log_key, "Unable to download binary for board {0}.".format(board))
                    return (repo_lock_token, False, True)
                binary = tmp_filename
                break
    if binary == None:
        redis.append(log_key, "Unable to find binary for board {0}.\n".format(board))
        return (repo_lock_token, False, True)
    test_config_ok = True
    tests_ok = True
    # Grab a lock on the device we're using for testing.
    print("waiting for device lock")
    try:
        with redis.lock("lock:" + board["board"] + "-" + str(board["path"]), timeout=15*60, blocking_timeout=20*60):
            print("device lock grabbed")
            # Run the tests.
            try:
                tests_ok = tester.run_tests(board, binary, test_cfg, log_key=log_key)
            except Exception as e:
                redis.append(log_key, "Exception while running tests on {0}:\n".format(board["board"]))
                redis.append(log_key, traceback.format_exc())
                test_config_ok = False
    except Exception as e:
         # Redis exception so don't log it.
         test_config_ok = False

    # Delete the binary since we're done with it.
    try:
        os.remove(binary)
    except FileNotFoundError:
        redis.append(log_key, "Unable to remove file: {0}\n".format(binary))
    return (repo_lock_token, test_config_ok, tests_ok)

# TODO(tannewt): Switch to separate queues if this causes lock contention.
@celery.task(bind=True, queue="low")
def start_test(self, repo, ref):
    base_repo = redis.get("source:" + repo).decode("utf-8")
    l = redis.lock(base_repo, timeout=60 * 60)
    log_key = "log:" + repo + "/" + ref
    log_url = "https://rosie-ci.ngrok.io/log/" + repo + "/" + ref
    print("grabbing lock " + base_repo)
    # Retry the task in 10 seconds if the lock can't be grabbed.
    if not l.acquire(blocking=False):
        if self.request.retries == 24:
            set_status(repo, ref, "error", log_url, "Hit max retries. Please ping the owner.")
        raise self.retry(countdown=30, max_retries=25)
    print("Lock grabbed " + base_repo)
    redis.set("owner-" + base_repo, log_url)
    set_status(repo, ref, "pending", log_url, "Commencing Rosie test.")
    repo_path = cwd + "/repos/" + base_repo
    os.chdir(repo_path)
    try:
        redis.append(log_key, git.checkout(ref))
    except sh.ErrorReturnCode_128 as e:
        print("error 128")
        redis.append(log_key, e.full_cmd + "\n" + e.stdout.decode('utf-8') + "\n" + e.stderr.decode('utf-8'))
        final_status(repo, ref, "error", "Git error in Rosie.")
    except sh.ErrorReturnCode_1 as e:
        print("error 1")
        redis.append(log_key, e.full_cmd + "\n" + e.stdout.decode('utf-8') + "\n" + e.stderr.decode('utf-8'))
        final_status(repo, ref, "error", "Git checkout error in Rosie.")
    print("test started " + log_url)
    return l.local.token.decode("utf-8")

@celery.task(queue="high")
def finish_test(results, repo, ref):
    base_repo = redis.get("source:" + repo).decode("utf-8")
    l = redis.lock(base_repo)
    l.local.token = results[0][0]
    print("releasing lock " + base_repo)
    try:
        l.release()
    except redis.exceptions.LockError:
        print("lock already released")

    test_config_ok = True
    tests_ok = True
    for result in results:
        test_config_ok = test_config_ok and result[1]
        tests_ok = tests_ok and result[2]

    if not test_config_ok:
        final_status(repo, ref, "error", "An error occurred while running the tests.")
    elif not tests_ok:
        final_status(repo, ref, "failure", "One or more tests failed.")
    else:
        final_status(repo, ref, "success", "All tests passed.")

def test_commit(repo, ref, tag):
    chain = start_test.s(repo, ref) | group(test_board.s(ref=ref, repo=repo, tag=tag, board=board) for board in config["devices"]) | finish_test.s(repo, ref)
    chain.delay()

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

    repo = data["repository"]["owner_name"] + "/" + data["repository"]["name"]
    build_number = data["id"]
    sha = data["commit"]
    if data["type"] == "pull_request":
        sha = data["head_commit"]
    tag = None
    if data["type"] == "push" and data["tag"] != None:
        tag = data["tag"]
    print(data)

    key = sha
    if tag is not None:
        key = tag

    upload_lock = "upload-lock:" + sha

    if data["state"] in ("started", ):
        print("travis started", key)
        # Handle pulls differently.
        if data["pull_request"]:
            load_code.delay(repo, "pull/" + str(data["pull_request_number"]) + "/head")
        elif data["tag"]:
            load_code.delay(repo, "refs/tags/" + tag)
        else:
            load_code.delay(repo, "refs/heads/" + data["branch"])
        redis.setex(upload_lock, 20 * 60, "locked")
        set_status(repo, sha, "pending", data["build_url"], "Waiting on Travis to complete.")
    elif data["state"] in ("passed", "failed"):
        print("travis finished")
        key = repo + "/" + key
        set_status(repo, sha, "pending", "https://rosie-ci.ngrok.io/log/" + key, "Queueing Rosie test.")
        redis.delete(upload_lock)
        test_commit(repo, sha, tag)
    elif data["state"] is ("cancelled", ):
        print("travis cancelled")
        redis.delete(upload_lock)
        set_status(repo, sha, "error", data["build_url"], "Travis cancelled.")
    elif data["status"] is None:
        set_status(repo, sha, "error", data["build_url"], "Travis error.")
    else:
        print("unhandled state:", data["state"])
        print(data)
    return jsonify({'status': 'received'})

@app.route("/upload/<sha>", methods=["POST"])
def upload_file(sha):
     if not redis.get("upload-lock:" + sha):
         abort(403)
     # check if the post request has the file part
     if 'file' not in request.files:
         abort(400)
     f = request.files['file']
     # if user does not select file, browser also
     # submit a empty part without filename
     if f.filename == '':
         abort(400)
     if f and f.filename == secure_filename(f.filename):
         filename = secure_filename(f.filename)
         # Store files in redis with an expiration so we hopefully don't leak resources.
         redis.setex("file:" + filename, 120 * 60, f.read())
         print(filename, "uploaded")
     else:
         abort(400)
     return jsonify({'msg': 'Ok'})

@app.route("/rerun/<owner>/<repo>/<sha>", methods=['GET'])
def rerun(owner, repo, sha):
    repo = owner + "/" + repo
    key = repo + "/" + sha
    set_status(repo, sha, "pending", "https://rosie-ci.ngrok.io/log/" + key, "Queueing manual Rosie test.")

    test_commit(repo, sha, None)
    return jsonify({"msg": "Ok"})

@app.route("/log/<owner>/<repo>/<sha>", methods=['GET'])
def log(owner, repo, sha):
    l = redis.get("log:" + owner + "/" + repo + "/" + sha)
    if not l:
        abort(404)
    return Response(l, mimetype='text/plain; charset=utf-8')
