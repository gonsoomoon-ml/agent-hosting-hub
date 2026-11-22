# release_review

변경 설명을 읽고 릴리스 규칙을 어겼는지 모델 호출 한 번으로 판단한다. 어겼으면 공유 도구로 검토 요청을 올리고, 결과를 답으로 돌려준다. LangGraph로 만든 흐름이 정해진 에이전트다. 허브가 호스팅하는 방식은 다른 에이전트와 같다.

## 노드(이 순서로 고정)

| 순서 | 노드 | 하는 일 |
|---|---|---|
| 1 | `read_change` | 입력을 정리한다. 모델도 도구도 부르지 않는다. |
| 2 | `check_rules` | 변경 설명과 규칙을 모델에 보내 `OK` 또는 `VIOLATION: <이유>`를 받는다. **모델을 부르는 유일한 노드**다. 모델 호출이 실패하면 `ERROR: ...`가 답이 된다. |
| 3 | `file_request` | 위반일 때만 `Release___file_review_request`를 부른다. **도구를 부르는 유일한 노드**다. |
| 4 | `report` | 판정과 요청 번호를 이어 답을 만든다(`<판정> Review request: <번호>`). 도구가 거부하거나 실패하면 요청 번호 대신 "요청을 올리지 못했다"는 사유를 답한다. 모델을 부르지 않는다. |

순서는 `graph.py`의 `build` 끝에 한 곳에 적혀 있다.

## 릴리스 규칙

`graph.py`의 `RELEASE_RULES`에 한 곳으로 적혀 있다.

1. 모든 변경은 전체 배포 전에 카나리 단계를 거친다.
2. 모든 변경에는 롤백 계획이 있다.
3. 모든 변경은 시험을 통과한다.

## 로컬에서 가짜 모델로 시험하기

```bash
uv run pytest tests/test_release_review.py -q
```

직접 돌려 보려면 모델과 도구를 가짜로 넘긴다.

```python
import sys; sys.path.insert(0, "dev_team/release_review")
import graph
g = graph.build(call_tool=lambda tool, args: '{"request_id": "RR-1"}',
                ask_model=lambda system, user: "VIOLATION: canary stage skipped")
print(g.invoke({"prompt": "Change C-7 skips the canary stage."})["answer"])
```

## 올리기

`main.py`와 `hub_tools.py`는 `dev_team/agent_template`의 복사본이다. 고치지 않는다(`tests/test_template_copies.py`가 같은지 확인한다). Runtime의 환경 변수 `HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME`을 쓴다.

```bash
dev_team/agent_template/publish.sh dev_team/release_review
```
