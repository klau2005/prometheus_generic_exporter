FROM python:3.13-trixie

LABEL maintainer="Claudiu Tomescu<klau2005@tutanota.com>"
LABEL version="0.10.0"

WORKDIR /prom_exporter

COPY . ./

RUN python3 -m pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

ENTRYPOINT [ "python3", "./prom_exporter.py" ]
