FROM ubuntu:16.04


ARG COTURN_VERSION=4.5.1.1

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    emacs-nox \
    build-essential \
    libssl-dev sqlite3 \
    libsqlite3-dev \
    libevent-dev \
    g++ \
    libboost-dev \
    libevent-dev \
    git


RUN git clone https://github.com/coturn/coturn.git

WORKDIR coturn

RUN git checkout $COTURN_VERSION && ./configure

RUN make && make install

RUN cp /coturn/examples/etc/*.pem .

ADD run.sh .

ENV PATH="/opt/bin64:${PATH}" \
    WEBRTC_TURN_REST_AUTH_SECRET=SHEPHERD

CMD bash -x /coturn/run.sh
