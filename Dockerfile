FROM python:3.5.3

WORKDIR /app

COPY requirements.txt /app

RUN pip install -r requirements.txt

COPY . /app

RUN python setup.py install

CMD python -u app.py

ENV REDIS_BROWSER_URL=redis://redis/0 \
    IDLE_TIMEOUT=60 \
    CONTAINER_DURATION=3600 \
    BROWSER_NET=shepherd_default \
    WEBRTC_HOST_IP=127.0.0.1 \
\
    PROXY_HOST='' \
    PROXY_PORT=8080 \
    PROXY_CA_URL=http://wsgiprox/download/pem \
    PROXY_CA_FILE=/tmp/proxy-ca.pem \
\
    HOME_TEMPLATE=shepherd.html \
    CONTROLS_TEMPLATE=shepherd.html \
    VIEW_TEMPLATE=browser_embed.html

