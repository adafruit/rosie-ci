# source .end/bin/activate # Get into the virtual environment
# source env.sh # Not in repo because it contains secrets.
# redis-server # Debian runs this automatically
# celery -A mike-ci.celery worker
export FLASK_APP=mike-ci.py
flask run
# ngrok http -subdomain=mike-ci 5000
