# quality_agent

검사 결과와 부품 사양에 대한 질문에 답하는 에이전트입니다. Strands로 만든 ReAct 에이전트라서, 모델이 질문을 보고 어떤 도구를 부를지 스스로 정하고 결과를 읽어 답합니다. 도구는 모두 허브의 도구 게이트웨이(`hub_tools.call_tool`)를 거칩니다. 질문마다 새 대화로 시작합니다.

## 도구 둘

| 도구 | 돌려주는 것 |
|---|---|
| `Quality___get_inspection_data` (`case_id`) | 검사 건의 부품 번호, 검사 결과, 검사원 사번 |
| `Parts___get_part_spec` (`part_id`) | 부품의 사양 |

도구가 `ERROR:`로 시작하는 답을 주면 호출이 거부되었거나 실패한 것입니다. 모델은 그대로 사용자에게 알리고, 자료를 지어내지 않습니다.

## 사번을 도구가 준 그대로 적는 이유

시스템 프롬프트는 검사 결과를 보고할 때 검사원 사번을 도구가 준 그대로 적게 합니다. 이후 데모에서 게이트웨이가 이 사번을 가립니다. 에이전트가 값을 줄이거나 바꿔 쓰면 가려진 결과를 눈으로 확인할 수 없습니다.

## 변형 둘

`variants/` 아래의 폴더 하나가 데모를 위한 버전 하나입니다. 올릴 때 변형의 파일이 같은 이름의 기본 파일을 대신합니다(`publish.sh`의 두 번째 인자). 둘 다 데모의 한 장면을 보여 주려고만 있습니다. **다른 에이전트의 바탕으로 쓰지 않습니다.**

### variants/v1-vulnerable

`requirements.txt`에 공개된 취약점이 있는 `jinja2==2.11.2`를 더한 변형입니다. 호스팅 심사의 스캔이 제출을 거부하는 모습을 보여 줍니다. 에이전트 코드는 같습니다.

### variants/v2-loop

사고가 나는 새 버전입니다. 승인된 `quality_agent`의 다음 버전으로 제출해, 질문 하나에서 에이전트가 같은 도구를 쉬지 않고 부르는 모습을 보여 줍니다. 다른 파일은 `agent.py` 하나입니다. 그 파일은 기본 `agent.py`를 통째로 복사하고 표시한 구간 하나(`# --- demo incident: asks again until the result is confirmed ---`부터 `# --- end of the demo incident ---`까지)를 더한 것이고, 구간 밖에서는 `run`이 그 구간의 함수를 부르는 한 줄만 다릅니다. 이 차이는 단위 테스트(`tests/test_quality_agent.py`)가 지킵니다.

- 데모의 이야기: 결과가 아직 나오지 않은 검사 건을 물으면 답이 확정될 때까지 처음부터 다시 묻는데, 그 반복에 횟수 제한이 빠졌습니다.
- 코드가 하는 일: `run`은 답에 `PENDING`이 있으면(대소문자를 가리지 않습니다) 같은 질문을 새 대화로 다시 묻습니다. 그래서 번마다 모델을 한 번 이상 부르고, 모델이 검사 건을 조회하면 도구를 한 번 부릅니다. 다시 물을 때마다 표준 출력에 `asking again (<n>)`을 출력합니다.
- 사고를 일으키는 질문은 `What is the result of inspection Q-1002?`입니다. 샘플 도구에서 `Q-1002`의 결과는 `PENDING`이고(`platform_team/sample_tools/tool_data.py`), 그 값은 바뀌지 않습니다.
- 2026-11-22의 두 실행에서, 확인 테스트가 이 질문을 실제 `quality_agent`에게 쉬지 않고 다시 물었을 때 한 번 물을 때마다 도구 호출이 하나였고, 1분에 47번과 39번이었습니다([확인 테스트](../../e2e_checks/spikes/README.md#결정)의 `LOOP_RATE`). 같은 날의 운영 확인(`make e2e-ops`)에서 이 변형을 허브에 올려 이 질문을 한 번 보냈습니다. 호출자는 20초 뒤에 포기했고, 에이전트는 그 뒤에도 다시 물었습니다. 22:11(UTC)의 1분과, 멈출 때까지의 22:12에 `asking again` 줄이 42개와 38개였고, 도구 게이트웨이의 그 도구 호출 수도 42와 38이었습니다. 플랫폼팀이 `stop.sh`로 멈출 때까지(호출에서 약 2분, 81번) 이어졌고, 멈춘 뒤 8초에 마지막 줄이 출력됐습니다.
- 호스팅 심사의 시험 호출은 부품 사양을 묻습니다(`What is the spec of part P-100?`). 그 답에는 보통 `PENDING`이 없으므로 이 변형은 시험 호출에서 다시 묻지 않고 심사를 지나도록 짜여 있습니다. 운영 확인에서 이 변형의 심사는 `SUCCEEDED`였습니다(304초, 시험 호출의 보통 질문 200).

#### `RETRY_SECONDS`: 데모의 안전장치

`RETRY_SECONDS`(환경 변수, 초, 기본값 600)는 이야기의 일부가 아닙니다. 첫 질문부터 이 시간이 지나면 더 묻지 않고 마지막 답을 돌려줍니다. 부른 쪽이 기다리다 그만둬도 반복은 멈추지 않기 때문에 둔 것입니다. 2026-11-22의 실행에서, 20초 만에 기다리기를 그만둔 호출 뒤에도 에이전트의 반복은 70~71초 더 돌아 제 끝까지 갔습니다([확인 테스트](../../e2e_checks/spikes/README.md#결정)의 `LONG_CALL`). 그래서 사고를 일으키는 데는 호출 한 번이면 되고, 아무도 멈추지 않은 반복을 끝내는 것은 이 시간 상한뿐입니다. 사고 한 번에 드는 모델 호출과 도구 호출도 이것으로 묶입니다.

허브는 Runtime에 이 변수를 주지 않습니다(심사의 배포 단계가 주는 환경 변수는 `HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME` 넷입니다). 그래서 Runtime에서는 기본값 600초입니다. 사고를 일으키는 호출을 보내는 쪽은 자기 클라이언트에 짧은 제한 시간을 둡니다.

### 고친 버전

고친 버전은 변형 없이 제출하는 기본 코드입니다. 기본 `run`은 한 번만 묻습니다(`ask_once`).

## 로컬에서 가짜로 테스트하기

```bash
uv run pytest tests/test_quality_agent.py -q
```

테스트는 도구 호출을 가짜로 바꾸고, 정해 둔 순서대로 답하는 가짜 모델을 Strands에 넘깁니다. 변형은 `publish.sh`가 올리는 것과 같은 코드 패키지(기본 파일 위에 변형의 파일)를 임시 폴더에 풀어서 테스트합니다. 직접 해 보려면 가짜 도구로 불러 봅니다.

```python
import sys; sys.path.insert(0, "dev_team/quality_agent")
import agent
agent.call_tool = lambda tool, args: '{"result": "PASS", "inspector_id": "EMP-204817"}'
print(agent.get_inspection_data("Q-1001"))
```

모델까지 쓰려면 `HUB_REGION`, `MODEL_ID`(추론 프로파일 ID)와 Bedrock 접근 권한이 필요합니다.

## 올리기

`main.py`와 `hub_tools.py`는 `dev_team/agent_template`의 복사본입니다. 고치지 않습니다. Runtime의 환경 변수 `HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME`을 씁니다.

```bash
dev_team/agent_template/publish.sh dev_team/quality_agent v1-vulnerable   # 심사가 거부합니다
dev_team/agent_template/publish.sh dev_team/quality_agent                 # 심사를 통과합니다. 고친 버전도 이것입니다
dev_team/agent_template/publish.sh dev_team/quality_agent v2-loop         # 사고가 나는 새 버전
```
