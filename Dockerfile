FROM ubuntu:16.04

LABEL maintainer="Claudiu <klau2005@gmail.com>"
LABEL version="0.8.3"

WORKDIR /prom_exporter

COPY . ./

RUN apt-get update \
    && apt-get install -y python3 python3-pip curl\
    && pip3 install setuptools\
    && pip3 install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD [ "python3", "./prom_exporter.py" ]
