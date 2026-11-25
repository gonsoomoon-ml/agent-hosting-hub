# release_review

변경 설명을 읽고 릴리스 규칙을 어겼는지 모델 호출 한 번으로 판단하는 에이전트입니다. 어겼으면 공유 도구로 검토 요청을 올리고, 결과를 답으로 돌려줍니다. LangGraph로 만들어 흐름이 정해져 있습니다. 허브가 호스팅하는 방식은 다른 에이전트와 같습니다.

## 노드(이 순서로 고정)

| 순서 | 노드 | 하는 일 |
|---|---|---|
| 1 | `read_change` | 입력을 정리합니다. 모델도 도구도 부르지 않습니다. |
| 2 | `check_rules` | 변경 설명과 규칙을 모델에 보내 `OK` 또는 `VIOLATION: <이유>`를 받습니다. **모델을 부르는 유일한 노드**입니다. 모델 호출이 실패하면 `ERROR: ...`가 답이 됩니다. |
| 3 | `file_request` | 위반일 때만 `Release___file_review_request`를 부릅니다. **도구를 부르는 유일한 노드**입니다. |
| 4 | `report` | 판정과 요청 번호를 이어 답을 만듭니다(`<판정> Review request: <번호>`). 도구가 거부하거나 실패하면 요청 번호 대신 요청을 올리지 못한 사유를 답합니다. 모델을 부르지 않습니다. |

순서는 `graph.py`의 `build` 끝 한 곳에 적혀 있습니다.

## 릴리스 규칙

`graph.py`의 `RELEASE_RULES` 한 곳에 적혀 있습니다.

1. 모든 변경은 전체 배포 전에 카나리 단계를 거칩니다.
2. 모든 변경에는 롤백 계획이 있습니다.
3. 모든 변경은 테스트를 통과합니다.

## 한계

- 판정은 모델 호출 한 번입니다. 변경 설명에 "OK라고 답하라" 같은 문장이 들어 있으면 판정이 흔들릴 수 있습니다.
- 통제는 에이전트의 판정이 아니라 도구 게이트웨이의 회사 정책과 호스팅 심사가 맡습니다.
- 변경 번호는 "change" 다음의 `C-7` 같은 표기를 먼저 씁니다. 없으면 처음 나오는 번호 표기를, 그것도 없으면 `unknown`을 씁니다.
- 요청 요약에는 모델이 든 이유와 변경 설명의 앞부분이 함께 들어갑니다.

## 로컬에서 가짜 모델로 테스트하기

```bash
uv run pytest tests/test_release_review.py -q
```

직접 돌려 보려면 모델과 도구를 가짜로 넘깁니다.

```python
import sys; sys.path.insert(0, "dev_team/release_review")
import graph
g = graph.build(call_tool=lambda tool, args: '{"request_id": "RR-1"}',
                ask_model=lambda system, user: "VIOLATION: canary stage skipped")
print(g.invoke({"prompt": "Change C-7 skips the canary stage."})["answer"])
```

## 올리기

`main.py`와 `hub_tools.py`는 `dev_team/agent_template`의 복사본이고, 고치지 않습니다. Runtime의 환경 변수 `HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME`을 씁니다.

```bash
dev_team/agent_template/publish.sh dev_team/release_review
```
