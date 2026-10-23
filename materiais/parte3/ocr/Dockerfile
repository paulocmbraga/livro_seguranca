FROM python@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr=5.3.0-2 tesseract-ocr-eng=1:4.1.0-2 && rm -rf /var/lib/apt/lists/*
USER 10001:10001
ENTRYPOINT ["tesseract"]
