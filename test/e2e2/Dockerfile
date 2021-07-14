FROM python:3.9-alpine

RUN apk add --no-cache bash curl

COPY --from=trajano/alpine-libfaketime /faketime.so /lib/libfaketime.so
RUN mkdir -p /etc/faketime

RUN mkdir /e2e
WORKDIR /e2e
COPY requirements.txt .
RUN python3 -m pip install -r requirements.txt

COPY apiwait .
COPY *.py .
COPY ./spec .

CMD ./apiwait 300 && python3 -m pytest -vv .
