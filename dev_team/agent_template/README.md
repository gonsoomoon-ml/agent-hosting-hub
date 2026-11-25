# 에이전트 템플릿

허브에 에이전트를 올리려는 개발 팀이 복사해서 시작하는 폴더입니다. 허브를 처음 보는 사람도 이 문서만 읽으면 올릴 수 있습니다.

## 파일

| 파일 | 설명 |
|---|---|
| `agent.py` | 팀이 씁니다(이 폴더에는 없습니다). `run(prompt) -> (answer, tools_used)` 함수 하나를 만듭니다. |
| `main.py` | Runtime의 진입점입니다. 요청을 받아 `agent.run`을 부르고 답을 돌려줍니다. 고치지 않습니다. |
| `hub_tools.py` | 허브의 공유 도구를 부르는 `call_tool(tool_id, arguments)`입니다. 거부나 실패는 예외 대신 `ERROR: ...`로 돌려줍니다. 그 글에 든 12자리 숫자(역할 ARN의 계정 ID 같은 것)는 `<ACCOUNT>`로 가립니다. |
| `agent.json` | 신청서입니다. 이름, 팀, 프레임워크, 쓸 도구의 목록이 들어 있습니다. |
| `requirements.txt` | 에이전트가 쓰는 패키지입니다. 아래 규칙을 지켜야 합니다. |
| `publish.sh` | 코드를 올리고 승인을 요청하는 명령입니다. |

## 템플릿이 하는 일

에이전트가 답하는 일은 팀의 코드(`agent.py`)가 합니다. 템플릿은 그 코드를 허브에 연결하는 틀입니다. 그래서 모든 팀의 에이전트가 같은 방식으로 제출되고, 심사를 받고, 호출되고, 도구를 씁니다.

```
템플릿 (모든 팀이 같습니다)
├── main.py        허브의 요청을 받아 run()을 부릅니다
├── agent.py       ← 팀이 씁니다: 프롬프트, 모델, 프레임워크, 어떤 도구를 언제 부를지
├── hub_tools.py   call_tool() 한 줄로 공유 도구를 부릅니다
└── publish.sh     명령 한 줄로 제출하고 승인을 요청합니다
```

`publish.sh`를 실행하면 아래 순서로 올라갑니다.

```
publish.sh my_agent
  ├─① 확인    agent.json의 이름 규칙, 도구가 카탈로그에 있는지
  ├─② 묶기    맨 위의 .py 파일과 requirements.txt → agent.zip
  ├─③ 올리기  제출 버킷의 submissions/<team>/<name>/agent.zip
  ├─④ 쓰기    카탈로그 레코드(신청서, 코드의 위치와 버전) → DRAFT
  └─⑤ 요청    승인 요청 → PENDING_APPROVAL
                 │
                 ▼
       호스팅 심사: Read → Scan → Grant → Deploy → Entry → TestCall → Approve
                 │
                 ▼
       Runtime <prefix>_<name>, 레코드 APPROVED
```

사용자의 질문 하나는 아래 길로 지나갑니다.

```
사용자의 질문
  │
  ▼
에이전트 게이트웨이 (허브의 통제가 걸리는 곳)
  │
  ▼
Runtime <prefix>_<name>
  ├─ main.py       invoke(payload)가 agent.run(prompt)을 부릅니다
  ├─ agent.py      팀의 코드가 call_tool("Parts___get_part_spec", {"part_id": "P-100"})을 부릅니다
  └─ hub_tools.py  MCP tools/call 요청에 SigV4 서명을 해서 보냅니다
       │
       ▼
     도구 게이트웨이 → 공유 도구 (신청서에 적은 도구만 부를 수 있습니다)

돌아오는 길: 도구의 답 또는 "ERROR: …" → agent.py → {"agent", "answer", "tools_used"} → 사용자
```

## 핵심 코드

아래는 줄여서 옮긴 것입니다. 전체는 각 파일에 있습니다.

`main.py`는 팀의 `run()`을 부르고, 답을 정해진 모양으로 돌려줍니다.

```python
app = BedrockAgentCoreApp()
NAME = os.environ.get("AGENT_NAME", "agent")      # the hub sets it from the application's name


@app.entrypoint
def invoke(payload, context=None):
    answer, tools_used = agent.run(str(payload.get("prompt", "")))
    return {"agent": NAME, "answer": answer, "tools_used": tools_used}
```

`hub_tools.py`의 `call_tool()`은 도구 이름과 인자로 MCP 요청을 만들고, SigV4로 서명해 도구 게이트웨이로 보냅니다. 실패해도 예외를 던지지 않고 `ERROR: …` 글을 돌려주므로, 모델이 그 글을 읽고 사용자에게 이유를 말할 수 있습니다.

```python
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool_id, "arguments": arguments}})
    try:
        credentials = boto3.Session(region_name=region).get_credentials()
        request = AWSRequest(method="POST", url=url, data=body, headers=headers)
        SigV4Auth(credentials.get_frozen_credentials(), SERVICE, region).add_auth(request)
        status, text = _post(url, dict(request.headers), body)
    except Exception as e:      # network, timeout, signing: told to the agent, not raised inside it
        return f"ERROR: could not reach the tool gateway: {error_text(e)}"
    answer = parse_tool_response(text)
```

팀이 쓰는 `agent.py`의 예는 [`quality_agent`](../quality_agent/agent.py)입니다. Strands 에이전트에 도구 둘을 주고, `run()`이 답과 부른 도구의 목록을 돌려줍니다. 템플릿과의 약속은 이 `run()` 하나입니다.

```python
@tool
def get_part_spec(part_id: str) -> str:
    return call_tool("Parts___get_part_spec", {"part_id": part_id})


def ask_once(prompt: str) -> tuple[str, list]:
    try:
        agent = new_agent()
        result = agent(prompt)
    except Exception as e:      # missing setting, model access, throttling: told to the caller, not raised
        return f"ERROR: {error_text(e)}", []
    return str(result).strip(), tools_called(agent.messages)


def run(prompt: str) -> tuple[str, list]:
    if not prompt.strip():
        return "ERROR: empty prompt", []
    return ask_once(prompt)
```

## 팀이 하는 일

1. 이 폴더를 복사합니다.
2. `agent.py`에 `run(prompt) -> (answer, tools_used)`를 씁니다. 도구는 `hub_tools.call_tool("Parts___get_part_spec", {"part_id": "P-100"})`처럼 부릅니다.
3. `agent.json`을 채웁니다(아래 "신청서의 규칙").
4. `publish.sh`를 실행합니다. 어느 폴더에서 실행해도 됩니다.

```bash
dev_team/agent_template/publish.sh <복사한 폴더>
```

`publish.sh`는 코드를 제출 버킷에 올리고, 신청서를 카탈로그에 쓰고, 승인을 요청합니다. 승인을 요청하면 호스팅 심사가 자동으로 시작합니다. 허브의 접두어와 리전은 `make`와 같은 규칙으로 리포의 `.env`에서 읽고([시작하기의 `.env`](../../docs/getting-started.md#env)), 어느 허브에 올렸는지 출력합니다.

## 코드의 규칙

- 코드는 폴더 맨 위의 `.py` 파일로 둡니다. 하위 폴더의 파일은 올라가지 않습니다.
- 폴더 맨 위의 `.py` 파일은 모두 올라가므로, 비밀 값을 코드에 적지 않습니다.
- `agent.py`가 `import`하는 패키지 가운데 표준 라이브러리가 아닌 것은 모두 `requirements.txt`에 적습니다.

## 신청서의 규칙

- 이름은 소문자로 시작하는 소문자와 숫자의 마디를 밑줄 하나로 이은 것이고, 3~31자입니다. `quality_agent`는 되고 `agent_1`, `Quality`, `quality__agent`는 안 됩니다.
- 허브는 이름으로 정책 이름(48자까지)과 Runtime 이름(`<prefix>_<에이전트>`)을 만듭니다. 정책 이름이 넘치면 `publish.sh`가 거부하고, 에이전트 이름이 몇 자까지 될 수 있는지 알려 줍니다.
- 도구는 카탈로그에 있는 `<Target>___<tool>` 이름입니다. 허브의 도구를 하나도 부르지 않는 에이전트는 빈 목록 `[]`을 적습니다(예: `dev_team/preloaded_agents/docs_adk`).

## 심사가 확인하고 거부하는 것

코드 패키지 맨 위에 `main.py`와 `requirements.txt`가 있어야 합니다. `requirements.txt`에는 패키지 색인에 있는 패키지를 이름으로 적고, 버전은 `==`로 고정합니다. 아래는 거부합니다.

| 거부하는 줄 | 이유 |
|---|---|
| pip 옵션(`-r`, `-e`, `--index-url`, `--hash`) | 설치 위치를 바꾸거나 다른 파일을 끌어올 수 있습니다. |
| 직접 참조(`pkg @ URL`, URL, `file:`, 경로) | 검사가 내용을 볼 수 없는 코드가 설치됩니다. |
| 환경 표시(`; python_version >= "3.10"`) | 검사와 배포가 서로 다른 기계를 기준으로 판단해, 검사에서 빠진 줄이 배포에서 설치될 수 있습니다. |

- Runtime은 Linux aarch64, CPython 3.13 하나이고, 설치는 그 환경의 wheel만 받습니다.
- Runtime에는 `requirements.txt`에 적은 패키지만 있습니다.
- 템플릿의 `bedrock-agentcore`, `boto3`, `botocore`는 `main.py`와 `hub_tools.py`가 쓰므로 지우지 않습니다.
- `aws-opentelemetry-distro`도 지우지 않습니다. 허브는 Runtime을 이 패키지의 명령 `opentelemetry-instrument main.py`로 실행해 trace를 내게 하고, 이 패키지 없이 실행해 본 적은 없습니다.

## 팀이 쓰지 않는 것

배포 설정과 실행 역할은 플랫폼이 만듭니다. 제출물에 배포 설정이 들어 있어도 쓰지 않습니다. Runtime에는 환경 변수 `HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME`이 들어 있습니다.
