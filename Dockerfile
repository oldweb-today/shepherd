FROM python:3.5.3

WORKDIR /app

COPY requirements.txt /app

RUN pip install -r requirements.txt

COPY . /app

RUN python setup.py install

CMD python -u app.py

ENV REDIS_BROWSER_URL redis://redis/0
ENV IDLE_TIMEOUT 60
ENV BROWSER_NET shepherd_default
ENV WEBRTC_HOST_IP 127.0.0.1

ENV PROXY_HOST ''
ENV PROXY_PORT 8080
ENV PROXY_CA_URL http://wsgiprox/download/pem
ENV PROXY_CA_FILE /tmp/proxy-ca.pem

ENV HOME_TEMPLATE shepherd.html
ENV CONTROLS_TEMPLATE shepherd.html
ENV VIEW_TEMPLATE browser_embed.html

