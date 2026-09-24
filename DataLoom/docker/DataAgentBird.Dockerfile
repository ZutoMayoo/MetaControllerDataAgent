FROM signalpilot-dbt-agent-clean:local

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATAAGENT_HOME=/output/dataagent_home

COPY runtime/dataagent /opt/dataagent
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install ormsgpack==1.12.2 && \
    python -m pip install "/opt/dataagent[nl2sql]"

COPY bird_gold_safe.py /opt/dataloom/bird_gold_safe.py
WORKDIR /opt/dataloom

ENTRYPOINT ["python", "/opt/dataloom/bird_gold_safe.py", "infer"]
