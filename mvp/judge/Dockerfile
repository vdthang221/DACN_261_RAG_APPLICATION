FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
COPY runner.py /runner.py
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "/runner.py"]
