"""Host-controlled Qwen SQL bridge: model gets evidence + read-only SQL only."""
from __future__ import annotations
import argparse, json, os, re, subprocess, urllib.request
from pathlib import Path

from contracts import require_ready_for_handoff

FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|grant|revoke|copy|call|do|truncate|vacuum)\b|;", re.I)

def sql_tool(sql: str) -> dict:
    sql = sql.strip()
    if sql.endswith(";") and ";" not in sql[:-1]:
        sql = sql[:-1].rstrip()
    if not re.match(r"^(select|with|explain)\b", sql, re.I) or FORBIDDEN.search(sql):
        return {"error": "only one read-only SELECT/WITH/EXPLAIN statement is allowed"}
    command = 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off -A -F "\\t"'
    result = subprocess.run(["docker", "exec", "-i", "codeaware-calcom-db", "sh", "-lc", command], input=sql, text=True, capture_output=True, timeout=35)
    text = (result.stdout if result.returncode == 0 else result.stderr).strip()
    return {"result": text[:12000], "truncated": len(text) > 12000}

TOOLS=[{"type":"function","function":{"name":"query_sql","description":"Execute exactly one read-only PostgreSQL SELECT/WITH/EXPLAIN query. Use information_schema to inspect schema.","parameters":{"type":"object","properties":{"sql":{"type":"string"}},"required":["sql"]}}}]
def call(messages, model, tools=True):
    body={"model":model,"messages":messages,"max_tokens":4096}
    if tools: body.update({"tools":TOOLS,"tool_choice":"auto"})
    request=urllib.request.Request(os.environ.get("DATALOOM_QWEN_URL","http://127.0.0.1:18020/v1/chat/completions"),data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(request,timeout=180) as response:return json.loads(response.read())
def main():
    p=argparse.ArgumentParser();p.add_argument("--task-spec",type=Path,required=True);p.add_argument("--evidence",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--model",required=True);a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    spec=json.loads(a.task_spec.read_text(encoding="utf-8")); evidence=json.loads(a.evidence.read_text(encoding="utf-8"))
    require_ready_for_handoff(evidence)
    prompt=f'''You are a PostgreSQL SQL generation role. Public task:\n{spec["extensions"]["task_markdown"]}\n\nTrusted project-understanding evidence:\n{json.dumps(evidence,ensure_ascii=False)}\n\nYou may inspect and query only the database through query_sql. Never request files, fixtures, validation, Gold, Docker, credentials, or non-read-only SQL. Your job is incomplete unless you submit one executable PostgreSQL SELECT/WITH query. At most 6 tool turns. At the final turn output only one SQL statement in a ```sql code block; no explanation, no JSON, and no more tool calls.'''
    messages=[{"role":"user","content":prompt}]; audit=[]; response_text=[]
    for turn in range(1,10):
        out=call(messages,a.model,tools=True); msg=out["choices"][0]["message"]; calls=msg.get("tool_calls",[]); response_text.extend([str(msg.get("content") or ""), str(msg.get("reasoning") or "")]); messages.append({k:msg[k] for k in ("role","content","tool_calls") if k in msg and msg[k] is not None});audit.append({"turn":turn,"calls":calls})
        if not calls:
            messages.append({"role":"user","content":"You have not submitted SQL. Return exactly one executable PostgreSQL SELECT/WITH statement in a ```sql code block now. No explanation and no tools."})
            out=call(messages,a.model,tools=False);msg=out["choices"][0]["message"];response_text.extend([str(msg.get("content") or ""), str(msg.get("reasoning") or "")]);messages.append({"role":"assistant","content":msg.get("content")});audit.append({"turn":"early-finalizer","calls":[]});break
        for item in calls:
            try: observation=sql_tool(json.loads(item["function"]["arguments"])["sql"])
            except Exception as exc: observation={"error":f"{type(exc).__name__}: {exc}"}
            messages.append({"role":"tool","tool_call_id":item["id"],"content":json.dumps(observation)})
        if turn==6:
            messages.append({"role":"user","content":"Tool budget complete. Submit exactly one executable PostgreSQL SELECT/WITH statement in a ```sql code block now. Do not explain and do not call tools."});out=call(messages,a.model,tools=False);msg=out["choices"][0]["message"];response_text.extend([str(msg.get("content") or ""), str(msg.get("reasoning") or "")]);messages.append({"role":"assistant","content":msg.get("content")});audit.append({"turn":"finalizer","calls":[]});break
    content="\n".join(response_text)
    (a.output/"raw_final.txt").write_text(content,encoding="utf-8")
    match=re.search(r'\{\s*"sql"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',content,re.S)
    fenced=re.findall(r'```(?:sql|postgresql)?\s*(.*?)```',content,re.I|re.S)
    if match: sql=json.loads('"'+match.group(1)+'"')
    elif fenced: sql=fenced[-1].strip()
    else:
        plain=re.findall(r'(?is)\b(?:with|select)\b.*',content)
        if not plain: raise ValueError("model did not return recognizable SQL")
        sql=plain[-1].strip()
    # A single terminal semicolon is conventional SQL formatting, not a second statement.
    if sql.endswith(";") and ";" not in sql[:-1]: sql=sql[:-1].rstrip()
    check=sql_tool(sql)
    a.output.mkdir(parents=True,exist_ok=True);(a.output/"candidate.sql").write_text(sql,encoding="utf-8");(a.output/"role_audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8");(a.output/"query_result.json").write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding="utf-8");(a.output/"conversation.json").write_text(json.dumps(messages,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        failure = os.environ.get("DATALOOM_FAILURE_PATH")
        if failure:
            Path(failure).write_text(json.dumps({"error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
