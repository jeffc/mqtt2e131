FROM python:latest

WORKDIR /code

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY mqtt2e131.py effects.py ./

CMD ["python", "run.py"]
