FROM python:latest

WORKDIR /run

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY mqtt2e131.py run.py ./

CMD ["python", "run.py"]
