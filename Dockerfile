FROM python:3.13-trixie

LABEL maintainer="Claudiu Tomescu<klau2005@tutanota.com>"
LABEL version="0.10.0"

WORKDIR /prom_exporter

COPY . ./

RUN pip3 install setuptools && pip3 install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD [ "python3", "./prom_exporter.py" ]
