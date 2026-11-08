FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=/usr/local/bin sh
RUN useradd -m app
USER app
WORKDIR /home/app
RUN arduino-cli core update-index && arduino-cli core install arduino:avr
RUN for L in "DHT sensor library" "Adafruit Unified Sensor" "LiquidCrystal I2C" "Keypad" "MFRC522" "Adafruit GFX Library" "Adafruit SSD1306" "Adafruit BusIO"; do arduino-cli lib install "$L" || true; done
COPY --chown=app server.py /home/app/server.py
ENV PORT=8080
CMD ["python", "/home/app/server.py"]
