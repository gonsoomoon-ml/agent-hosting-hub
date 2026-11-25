# spec_assistant

부품의 사양과 시험 결과를 묻는 질문에 답하는 에이전트입니다. 코드가 없는 AgentCore managed harness로, 모델, 시스템 프롬프트, 쓸 도구로만 정의됩니다. 모델을 부르고 도구를 고르는 반복은 AgentCore가 합니다. 허브에 미리 올려 둔 에이전트 둘 가운데 하나이고, 다른 하나는 [docs_adk](../docs_adk/README.md)입니다.

## 신청서

`agent.json`입니다. 다른 신청서의 칸에 지시문 `system_prompt`가 더 있습니다. 프레임워크는 `harness`, 도구는 공유 도구 둘(`Parts___get_part_spec`, `Parts___get_test_result`)입니다. 코드가 없으므로 `publish.sh`로 올리지 않습니다.

## 심사를 거치지 않습니다

검사하고 올릴 코드가 없으므로 심사는 이 레코드를 건너뛰고 `Skipped`로 끝납니다(알림 없음). 대신 `make preload`가 플랫폼팀의 자격 증명으로 아래를 만듭니다(`platform_team/hosting_review/preload_agents.py`의 `host_harness`).

| 순서 | 만드는 것 | 이름 |
|---|---|---|
| 1 | 먼저 신청서를 확인합니다. 맞지 않으면 아무것도 만들지 않습니다. | |
| 2 | 실행 역할. 다른 에이전트와 권한도 권한 경계도 같습니다([에이전트 실행 역할의 상한](../../../platform_team/hosting_review/README.md#에이전트-실행-역할의-상한권한-경계)). | `<prefix>-agent-spec_assistant-role` |
| 3 | 신청서의 도구마다 도구 게이트웨이의 permit | `tool_spec_assistant_Parts_get_part_spec`, `tool_spec_assistant_Parts_get_test_result` |
| 4 | harness(`CreateHarness`). 모델은 허브의 `MODEL_ID`, 도구는 도구 게이트웨이 하나(이름 `hub_tools`)이고, 메모리는 끕니다. | `<prefix>_spec_assistant` |
| 5 | SSM에 적은 harness의 ARN | `/<prefix>/agents/spec_assistant/harness_arn` |
| 6 | 승인된 카탈로그 레코드 | 레코드 `spec_assistant` |

- 쓸 수 있는 도구(`allowedTools`)는 신청서의 도구를 `@hub_tools/<도구>`로 적은 것뿐입니다. AgentCore 개발자 안내서는 이것을 비우거나 `"*"`로 두면 셸, 파일 읽고 쓰기 같은 기본 도구를 쓴다고 적습니다.
- `make preload`를 다시 돌려도 있는 harness는 실행 역할과 permit까지 그대로입니다. 그래서 `agent.json`이나 `MODEL_ID`를 바꿔도 반영되지 않습니다(코드가 그렇게 하고, 바꿔 본 적은 없습니다).
- 바꾼 것을 쓰려면 `make destroy`로 허브를 지우고 `make deploy`, `make seed`, `make preload`로 다시 올립니다. 에이전트 하나만 지우는 명령은 없습니다(`reject.sh`는 승인된 에이전트를 거부합니다).

## 부르는 법

harness는 에이전트 게이트웨이 뒤에 있지 않고, AgentCore의 `InvokeHarness`로 부릅니다. 허브의 역할 가운데 `bedrock-agentcore:InvokeHarness`를 가진 것은 없어서, 부를 수 있는 것은 그 권한을 가진 플랫폼팀의 자격 증명뿐입니다. AgentCore 개발자 안내서는 `bedrock-agentcore:InvokeAgentRuntime`도 필요하다고 적습니다(확인하지 않았습니다).

```bash
uv run python -c "
from platform_team.hosting_review.preload_agents import ask_harness
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
s = Settings.from_env(); c = Clients.for_settings(s)
arn = c.ssm.get_parameter(Name=s.ssm('agents', 'spec_assistant', 'harness_arn'))['Parameter']['Value']
print(ask_harness(c, arn, 'What is the spec of part P-100?'))"
```

`ask_harness`는 새 세션으로 질문 하나를 보내고, 돌아오는 stream의 글을 이어 돌려줍니다. 사용량 보고(`usage.sh`)는 harness가 도는 Runtime `harness_<prefix>_spec_assistant`의 메트릭을 표에 `spec_assistant`로 넣습니다.

## 허브에서 받는 통제

- 진입 target이 없어 진입 정책, 비밀값 검사, 전사 정책, 커스텀 가드레일이 닿지 않습니다. 멈춤 명령(`stop.sh`)은 이 에이전트를 거부합니다.
- 도구 게이트웨이를 지나는 도구 호출은 실행 역할의 permit 둘에 묶입니다. `allowedTools`는 모델에게 보여 줄 도구를 고르는 설정이고 권한이 아닙니다.
- `InvokeHarness`는 호출마다 `tools`, `allowedTools`, `systemPrompt`, `model`을 받으므로, 부를 수 있는 사람은 이것들을 바꿔 보낼 수 있습니다. 도구 게이트웨이 밖의 도구(`remote_mcp`, `agentcore_browser`, `agentcore_code_interpreter`, `inline_function`)와 기본 도구에는 permit이 닿지 않습니다.
- 해 본 것은 `allowedTools`에 permit이 없는 도구를 더해 두 번 묻기뿐입니다. 모델이 그 도구를 부르지 않아 도구 게이트웨이의 거부는 보지 못했고, `tools`, `systemPrompt`, `model`을 바꿔 보내는 것은 해 보지 않았습니다.

## AWS에서 본 것

2026-11-22에 `us-west-2`, 접두어 `hub`, 기본 모델로 돌렸습니다.

- `make preload`가 시작하고 harness가 `READY`, 레코드가 `APPROVED`가 되기까지 약 5분(288초)이었습니다.
- `What is the spec of part P-100?`에는 도구 `Parts___get_part_spec`을 불러 `M4 x 12 mm`가 든 답을 했습니다. 허락하지 않은 도구가 필요한 질문에는 도구를 부르지 않았습니다.
- AgentCore는 harness를 Runtime `harness_hub_spec_assistant` 위에서 돌립니다. 허브의 이름(`hub_…`)과 모양이 달라서 `check_cleanup.py`가 이 모양도 찾습니다.
- 실행 역할에는 AWS의 harness 실행 역할 예시에 있는 ECR Public 권한이 없습니다. 그래도 harness는 모델과 도구 게이트웨이를 불렀습니다.
- `make destroy`가 harness와 이 에이전트의 실행 역할, 도구 정책, SSM 값, 레코드를 지웠고, `check_cleanup.py`가 `still present: nothing`을 출력했습니다.
