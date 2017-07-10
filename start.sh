# source env.sh # Not in repo because it contains secrets.
# redis-server
# celery -A mike-ci.celery
export FLASK_APP=mike-ci.py
flask run
# ngrok http -subdomain=mike-ci 5000
