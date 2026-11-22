# quality_agent

검사 결과와 부품 사양에 대한 질문에 답하는 에이전트다. Strands로 만든 ReAct 에이전트라서, 모델이 질문을 보고 어떤 도구를 부를지 스스로 정하고 결과를 읽어 답한다. 도구는 모두 허브의 도구 게이트웨이(`hub_tools.call_tool`)를 거친다. 질문마다 새 대화로 시작한다.

## 도구 둘

| 도구 | 돌려주는 것 |
|---|---|
| `Quality___get_inspection_data` (`case_id`) | 검사 건의 부품 번호, 검사 결과, 검사원 사번 |
| `Parts___get_part_spec` (`part_id`) | 부품의 사양 |

도구가 `ERROR:`로 시작하는 답을 주면 호출이 거부되었거나 실패한 것이다. 모델은 그대로 사용자에게 알리고, 자료를 지어내지 않는다.

## 사번을 도구가 준 그대로 적는 이유

시스템 프롬프트는 검사 결과를 보고할 때 검사원 사번을 도구가 준 그대로 적게 한다. 이후 데모에서 게이트웨이가 이 사번을 가린다. 에이전트가 값을 줄이거나 바꿔 쓰면 가려진 결과를 눈으로 확인할 수 없다.

## variants/v1-vulnerable

`requirements.txt`에 공개된 취약점이 있는 `jinja2==2.11.2`를 더한 변형이다. 호스팅 심사의 스캔이 제출을 거부하는 모습을 보여 주려고만 있다. 에이전트 코드는 같다. **다른 에이전트의 바탕으로 쓰지 않는다.** 올릴 때 변형의 파일이 기본 파일을 대신한다.

## 로컬에서 가짜로 시험하기

```bash
uv run pytest tests/test_quality_agent.py -q
```

시험은 도구 호출을 가짜로 바꾸고, 정해 둔 순서대로 답하는 가짜 모델을 Strands에 넘긴다. 직접 해 보려면 가짜 도구로 불러 본다.

```python
import sys; sys.path.insert(0, "dev_team/quality_agent")
import agent
agent.call_tool = lambda tool, args: '{"result": "PASS", "inspector_id": "EMP-204817"}'
print(agent.get_inspection_data("Q-1001"))
```

모델까지 쓰려면 `HUB_REGION`, `MODEL_ID`(추론 프로파일 ID)와 Bedrock 접근 권한이 필요하다.

## 올리기

`main.py`와 `hub_tools.py`는 `dev_team/agent_template`의 복사본이다. 고치지 않는다. Runtime의 환경 변수 `HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME`을 쓴다.

```bash
dev_team/agent_template/publish.sh dev_team/quality_agent v1-vulnerable   # 심사가 거부한다
dev_team/agent_template/publish.sh dev_team/quality_agent                 # 심사를 통과한다
```
