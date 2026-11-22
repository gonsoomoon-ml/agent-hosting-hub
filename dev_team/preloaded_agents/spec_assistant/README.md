# spec_assistant

부품의 사양과 시험 결과를 묻는 질문에 답하는 에이전트다. 코드가 없는 AgentCore managed harness다. 모델, 시스템 프롬프트, 쓸 도구로만 정의되고, 돌리는 일(모델을 부르고 도구를 고르고 결과를 넘기는 반복)은 AgentCore가 한다. 허브에 처음부터 올라와 있는 두 에이전트 가운데 하나로, 플랫폼팀의 `make preload`가 플랫폼팀의 자격 증명으로 올린다(`platform_team/hosting_review/preload_agents.py`의 `host_harness`). 다른 하나인 [docs_adk](../docs_adk/README.md)는 코드가 있어 다른 팀의 에이전트와 같은 심사를 거친다.

## 신청서

`agent.json`이다. 다른 신청서와 같은 칸(이름, 팀, 프레임워크, 설명, 도구)에 harness의 지시문 `system_prompt`가 더 있다. 프레임워크는 `harness`이고, 도구는 카탈로그의 공유 도구 둘(`Parts___get_part_spec`, `Parts___get_test_result`)이다. 폴더에 코드가 없으므로 `publish.sh`로 올리지 않는다.

## 심사를 거치지 않는다

호스팅 심사는 제출된 코드를 검사하고 묶어 Runtime으로 올리는 과정이다. harness에는 그 코드가 없다. 그래서 심사의 Read는 신청서의 `framework`가 `harness`인 record를 건너뛰고, 심사는 `Skipped`로 끝난다(알림 없음). 심사가 하던 일 가운데 이 에이전트에 필요한 것은 `host_harness`가 플랫폼팀의 자격 증명으로 한다. 심사의 역할을 쓰지 않는다.

| 순서 | 하는 일 | 이름 |
|---|---|---|
| 1 | 신청서를 확인한다. 신청서의 규칙(이름, 카탈로그의 도구, 정책 이름의 길이)에 더해, 프레임워크가 `harness`이고 `system_prompt`가 있고 harness 이름이 40자(`CreateHarness`가 받는 길이) 안이어야 한다. 그 이름의 역할, Runtime, harness가 이미 있으면 허브의 것인지 읽어서 확인한다(정리와 같은 확인). 맞지 않으면 아무것도 만들지 않고 멈춘다. | |
| 2 | 실행 역할을 만든다. 심사의 Grant가 에이전트 역할을 만드는 함수(`review_steps.ensure_agent_role`, 권한은 `_execution_role`)로, 같은 권한 경계를 달아 만든다. 그래서 다른 에이전트의 실행 역할과 권한이 같다([호스팅 심사, 에이전트 실행 역할의 상한](../../../platform_team/hosting_review/README.md#에이전트-실행-역할의-상한권한-경계)). | `<prefix>-agent-spec_assistant-role` |
| 3 | 신청서의 도구마다 도구 게이트웨이에 permit을 건다. Grant가 거는 것과 같다. | `tool_spec_assistant_Parts_get_part_spec`, `tool_spec_assistant_Parts_get_test_result` |
| 4 | harness를 만든다(`CreateHarness`). 모델은 허브의 `MODEL_ID`, 지시문은 신청서의 `system_prompt`, 도구는 도구 게이트웨이 하나다(이름 `hub_tools`, 실행 역할로 SigV4 서명). 쓸 수 있는 도구(`allowedTools`)는 신청서의 도구뿐이다(`@hub_tools/Parts___get_part_spec`, `@hub_tools/Parts___get_test_result`). 메모리는 끈다(`memory: disabled`). `READY`가 될 때까지 기다린다. | `<prefix>_spec_assistant` |
| 5 | harness의 ARN을 SSM에 적는다. | `/<prefix>/agents/spec_assistant/harness_arn` |
| 6 | 카탈로그 record를 쓰고 승인을 요청한 뒤(이때 심사가 시작해 건너뛴다) 승인한다. 사유는 `preloaded by the platform team`이다. | record `spec_assistant` |

이미 있는 것은 그대로 둔다. 승인된 record와 이 이름의 harness가 있으면 다시 만들지 않는다. 역할의 inline 정책은 Grant처럼 매번 다시 쓰고, SSM 값(`harness_arn`)도 매번 같은 값으로 다시 쓴다.

신청서(`agent.json`)를 바꾼 뒤 `make preload`를 다시 돌리면 일부만 반영된다. 승인된 record와 harness는 그대로 두므로 바뀐 설명, 지시문, 쓸 수 있는 도구(`allowedTools`)는 반영되지 않는다. 새로 적은 도구에는 permit이 걸리고, 빠진 도구의 permit은 지우지 않으므로 남는다(Grant는 지운다). 그러면 실행 역할이 record와 harness에 없는 도구의 permit을 가질 수 있다. 코드가 그렇게 하고, 해 보지 않았다. 바뀐 신청서를 쓰려면 이 에이전트를 먼저 지운다. 지금 에이전트 하나만 지우는 명령은 없으므로(`reject.sh`는 승인된 에이전트를 거부한다) `make destroy`로 허브를 지우고 다시 올린다.

`allowedTools`에는 신청서의 도구를 `@hub_tools/<도구>`로 하나씩 적는다. AgentCore 개발자 안내서("Tools", 2026-11-22에 읽었다)는 게이트웨이의 도구를 `@<서버>/<도구>`로 고르고, 앞에 `@`가 없는 이름은 기본 도구를 고르며, `allowedTools`를 비우거나 `"*"`로 두면 harness가 추천하는 기본 도구(셸, 파일 읽고 쓰기 같은)를 쓴다고 적는다. 그래서 비우거나 `"*"`로 두지 않는다. 기본 도구에 대한 것은 여기서는 확인하지 않았다. 2026-11-22의 실행에서는 `@hub_tools/` 모양이 게이트웨이의 도구를 골랐다(아래). 메모리를 끄는 것은, 같은 안내서("Memory")가 서비스 API로 만들 때 메모리 설정을 빼면 서비스가 managed memory를 만든다고 적기 때문이다. 이것은 여기서는 확인하지 않았다(메모리를 끈 harness만 만들었다). 이 에이전트는 질문마다 새 세션이라 메모리가 쓸모없다. 메모리를 끈 harness에 managed memory가 생기지 않은 것은 아래의 실행에서 봤다.

## 부르는 법

harness는 에이전트 게이트웨이 뒤에 있지 않다. AgentCore의 `InvokeHarness`로 부른다.

```bash
uv run python -c "
from platform_team.hosting_review.preload_agents import ask_harness
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
s = Settings.from_env(); c = Clients.for_settings(s)
arn = c.ssm.get_parameter(Name=s.ssm('agents', 'spec_assistant', 'harness_arn'))['Parameter']['Value']
print(ask_harness(c, arn, 'What is the spec of part P-100?'))"
```

`ask_harness`는 새 세션으로 질문 하나를 보내고, 돌아오는 stream의 글(`contentBlockDelta`의 `text`)을 이어 돌려준다. stream에 오류가 오면 그 내용으로 예외를 낸다. 호출에 도구, 모델, 지시문을 따로 싣지 않으므로 harness의 설정이 그대로 쓰인다. AgentCore 개발자 안내서("Security and access controls", 2026-11-22에 읽었다)는 `InvokeHarness`에 `bedrock-agentcore:InvokeHarness`와 `bedrock-agentcore:InvokeAgentRuntime`이 필요하다고 적는다. 여기서는 확인하지 않았다. 허브의 역할 가운데 `bedrock-agentcore:InvokeHarness`를 가진 것은 없다(Terraform의 정책에 이 action이 없다). 그래서 허브 안에서 이 에이전트를 부를 수 있는 것은 그 권한을 가진 플랫폼팀의 자격 증명뿐이다. 사용량 보고(`usage.sh`)는 harness가 도는 Runtime(아래와 같이 이름이 `harness_<prefix>_spec_assistant`다)으로 이 에이전트를 찾아, 그 Runtime의 이름으로 메트릭을 읽고 표에 `spec_assistant`로 넣는다. 코드가 그렇게 한다. 2026-11-22의 운영 확인에서 그 Runtime의 메트릭은 사용량 보고가 읽는 모양(`Name=harness_hub_spec_assistant::DEFAULT`, `Operation=InvokeAgentRuntime`, `Resource=<Runtime ARN>`)으로 있었고, `usage.sh 60`이 이 에이전트를 3번, 세션 3으로 보였다(아래).

## 허브에서 받는 통제

에이전트 게이트웨이에 진입 target이 없으므로 진입의 통제를 받지 않는다. 진입 정책, 비밀값 검사, 전사 정책(`rollout.sh`), 커스텀 가드레일이 이 에이전트에 닿지 않고, 멈춤 명령(`stop.sh`)도 이 에이전트를 거부한다. 도구 호출은 도구 게이트웨이를 지나므로, 실행 역할에 걸린 도구 permit 둘만큼만 도구를 부를 수 있다. `allowedTools`는 harness가 모델에게 보여 줄 도구를 고르는 설정이고 권한이 아니다. 서비스 모델(botocore 1.44.9)의 `InvokeHarness`는 호출마다 `tools`, `allowedTools`, `systemPrompt`, `model`을 받으므로, `InvokeHarness`를 부를 수 있는 사람은 호출에서 이것들을 바꿔 보낼 수 있다. 그래도 도구 게이트웨이를 지나는 호출은 이 역할의 permit에 묶인다. 호출에서 바꿔 보내는 것은 `allowedTools` 하나만, 한 번 해 봤다(아래의 운영 확인). 모델이 그 도구를 부르지 않았으므로 도구 게이트웨이가 permit이 없는 호출을 거부하는지는 그때도 보지 못했다. `tools`, `systemPrompt`, `model`을 바꿔 보내는 것은 해 보지 않았다.

## 2026-11-22의 실행에서 본 것

`us-west-2`, 접두어 `hub`, 모델은 기본값(`us.anthropic.claude-haiku-4-5-20251001-v1:0`)이다. 빈 계정에서 `AUTO_APPROVE=1 make deploy seed preload`를 한 번 돌렸다.

- `make preload`가 시작하고 harness가 `READY`, record가 `APPROVED`가 되기까지 288초였다. 역할과 도구 정책은 새로 만들었다.
- AgentCore는 harness를 Runtime 하나 위에서 돌린다. 그 Runtime의 이름은 `harness_hub_spec_assistant`였고 `ListAgentRuntimes`에 나왔다(`GetHarness`의 `environment.agentCoreRuntimeEnvironment`도 그 이름과 ID를 적는다). 그 Runtime의 workload identity는 `harness_hub_spec_assistant-<10자>`, 로그 그룹은 `/aws/bedrock-agentcore/runtimes/harness_hub_spec_assistant-<10자>-DEFAULT`였다. 허브가 만드는 이름(`hub_…`)과 모양이 달라서 정리(`agent_cleanup`)와 남은 것 찾기(`check_cleanup.py`)가 이 모양도 본다. managed memory는 생기지 않았다.
- record의 승인 요청으로 심사가 시작했고, Read, `Reviewable`, `Skipped`를 지나 0.7초 만에 `SUCCEEDED`로 끝났다.
- `ask_harness`로 `What is the spec of part P-100?`를 묻자 6.2초 만에 `M4 x 12 mm`와 `Steel`이 든 답이 왔다. 같은 질문의 stream을 따로 읽어 보니 모델은 도구 `Parts___get_part_spec`(게이트웨이의 이름 그대로, `@hub_tools/`는 붙지 않는다)를 `{"part_id": "P-100"}`로 불렀고, 도구 게이트웨이를 지난 샘플 도구의 답(`{"part_id":"P-100","spec":"M4 x 12 mm, steel","synthetic":true}`)이 tool result로 왔다. 첫 모델 호출의 입력은 775 토큰이었다.
- 허락하지 않은 도구 `Quality___get_inspection_data`가 필요한 질문(`What is the result of inspection case Q-1001, and which inspector did it? Use the inspection data tool.`)에는 도구를 하나도 부르지 않았다. 두 번 물었고(stream을 읽은 한 번과 `ask_harness`로 한 번), 두 번 다 모델은 자기에게 있는 도구는 `Parts___get_part_spec`과 `Parts___get_test_result`뿐이라고 답하고 부품 ID를 물었다. 그래서 `allowedTools`가 그 도구를 모델의 도구 목록에서 뺀 것으로 본다. 모델이 그 도구를 부르려 하지 않았으므로, 도구 게이트웨이가 permit이 없는 이 역할의 호출을 거부하는지는 이 실행으로 확인되지 않았다.
- 실행 역할은 다른 에이전트의 실행 역할과 같은 문장들이다. 그 역할로 harness가 만들어지고 모델과 도구 게이트웨이를 불렀다. harness가 도는 Runtime의 로그 그룹에 거부된 줄이나 오류 줄은 없었다. AWS의 harness 실행 역할 예시에 있는 ECR Public 권한(`ecr-public:GetAuthorizationToken`, `sts:GetServiceBearerToken`)은 이 역할에 없다. 역할이 토큰을 받을 수 있는 workload identity는 `hub_spec_assistant-*`(Runtime 에이전트의 모양)이라 harness의 것(`harness_hub_spec_assistant-<10자>`)과 맞지 않는다. 그래도 위의 호출이 됐으므로 이 harness는 그 토큰을 쓰지 않은 것으로 본다(게이트웨이는 실행 역할로 SigV4 서명한다).
- `make preload`를 다시 돌리자 4초 만에 끝났고 `(kept)`를 찍었다. 앞뒤로 비교한 것(harness의 버전과 시각, record의 상태와 시각, 정책 목록, Runtime의 버전, 심사 실행의 수, 올린 코드의 version 수)이 그대로였다. 역할의 inline 정책과 SSM 값은 비교하지 않았다(둘 다 같은 값으로 다시 쓴다).
- `make destroy`가 이 에이전트의 도구 정책 둘, harness(`DeleteHarness`, 사라질 때까지 기다린다), harness가 돌던 Runtime의 로그 그룹, 실행 역할, SSM 값, record를 지웠다. harness가 돌던 Runtime과 그 workload identity는 harness와 함께 사라졌다. 끝에 `check_cleanup.py`가 `still present: nothing`을 찍었고, 목록으로도 harness, `hub_`나 `harness_`로 시작하는 Runtime과 workload identity가 남지 않은 것을 봤다.

## 2026-11-22의 운영 확인에서 본 것

같은 날 `make e2e-ops`(`e2e_checks/e2e_operations.py`)가 `make preload`로 이 에이전트를 올렸다. 그때 허브에는 커스텀 가드레일과 적용 모드의 전사 정책 `guard_prompt`가 켜져 있었다. 둘 다 에이전트 게이트웨이에 걸리므로 이 에이전트에는 닿지 않는다.

- `What is the spec of part P-100?`에 도구 `Parts___get_part_spec`을 불러 `M4 x 12 mm, steel`이 든 답을 했다(stream으로 읽었다).
- 호출에서 쓸 수 있는 도구의 목록(`allowedTools`)에 permit이 없는 도구를 더해 한 번 물었다. 목록은 `@hub_tools/Parts___get_part_spec`, `@hub_tools/Parts___get_test_result`, `@hub_tools/Quality___get_inspection_data`였고, 질문은 `What is the result of inspection Q-1001?`이었다. stream에 도구 호출이 없었다. 모델은 검사 ID로 찾는 도구가 없고 부품 ID로 찾는 도구만 있다고 답했다. 그 시간 동안 도구 게이트웨이에는 `tools/list`가 셋 있었고(이 harness를 세 번 불렀다), 그때마다 `AgentCore.Gateway.ListTools`와 `AgentCore.Policy.PartiallyAuthorizeActions`의 span이 있었다. 이 둘이 무엇을 거르는지는 확인하지 않았다.
- `quality_agent`가 `stop.sh`로 멈춰 있는 동안 같은 질문에 답했다(`M4 x 12 mm`).
- `usage.sh 60`의 표에 `spec_assistant 3 3 0 0.000000 0.000000`이 있었다(부른 수, 세션, 오류, CPU, 메모리). 같은 허브에서 다시 돌린 두 번째 실행에서는 `spec_assistant 6 6 0 0.028382 1.744684`였다. CPU와 메모리도 harness가 도는 Runtime의 이름으로 읽혔다.
- 같은 허브에서 `make e2e-ops`를 다시 돌릴 때 `make preload`는 이 에이전트를 그대로 두었다.
