# source .end/bin/activate # Get into the virtual environment
# source env.sh # Not in repo because it contains secrets.
# redis-server # Debian runs this automatically
# celery -A rosie-ci.celery worker
export FLASK_APP=rosie-ci.py
flask run
# ngrok http -subdomain=rosie-ci 5000
