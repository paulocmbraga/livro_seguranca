FROM python@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
WORKDIR /lab
COPY probe.py receiver.py public.txt private.txt /lab/
RUN chmod 555 /lab /lab/probe.py /lab/receiver.py && chmod 444 /lab/public.txt && chmod 600 /lab/private.txt
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "/lab/probe.py"]
