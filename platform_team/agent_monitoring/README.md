# 모니터링

허브의 알림이 모이고, 올라온 에이전트가 무엇을 했는지 플랫폼팀이 보는 곳입니다. 이 모듈은 알림 주제와 수신함, 도구 호출 경보, 두 게이트웨이의 로그와 trace 전달을 만듭니다. 사용량 보고(`usage.sh`)는 에이전트와 도구가 몇 번 불렸는지를 메트릭에서 읽어 표로 출력합니다.

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 흐름 2의 "모니터링" 상자입니다. ⑩ "기록 수집"과 ⑪ "이상 탐지 알림"의 자리입니다.

## 알림

- 알림 주제는 SNS 주제 `<prefix>-alerts`입니다. 기본 허브에서는 SQS 수신함 `<prefix>-alerts-inbox`가 구독하고, 이 저장소의 어느 명령도 이 수신함을 읽지 않습니다.
- 메일로 받으려면 Terraform 변수 `alert_email`에 주소를 줍니다.
- 이 주제로 오는 알림은 셋입니다. 도구 호출 경보, [커스텀 가드레일](../custom_guardrail/README.md)의 오류 경보(`<prefix>-guardrail-errors`), 호스팅 심사의 실패 알림입니다.
- 확인 스크립트는 임시 큐 `<prefix>-e2e-alerts`를 만들어 이 주제를 구독하고, 끝나면 지웁니다.

## 도구 호출 경보

에이전트 하나가 같은 질문을 쉬지 않고 다시 묻는 사고를 플랫폼팀에 알립니다. 그런 에이전트는 다시 물을 때마다 도구를 부르므로, 한 도구의 1분 호출 수가 평소보다 훨씬 많아집니다. 경보는 알리기만 하고, 에이전트를 멈추는 것은 플랫폼팀의 명령입니다([에이전트 멈추기와 재개](../agent_stop/README.md)).

| | |
|---|---|
| 경보 | `<prefix>-tool-calls` |
| 보는 것 | 도구 게이트웨이가 도구마다 남기는 호출 수. 네임스페이스 `AWS/Bedrock-AgentCore`, 메트릭 `Invocations`, 차원 `Method=tools/call` |
| 지켜보는 도구 | 변수 `watched_tool`. 기본값은 `Quality___get_inspection_data`(검사 건 조회) |
| 울리는 때 | 1분 합계가 변수 `tool_calls_per_minute`(기본값 19)보다 클 때 |
| 데이터가 없는 분 | 정상으로 봅니다(`notBreaching`) |
| 알리는 곳 | `<prefix>-alerts` |

- 메트릭은 부른 에이전트를 나눠 세지 않습니다. 이 저장소에서 신청서에 이 도구를 적은 에이전트는 `quality_agent` 하나라서, 경보가 울리면 그 에이전트의 호출입니다.
- 임계값 19는 2026-11-22에 잰 사고의 반복(1분에 47번과 39번)에서 낮은 쪽의 절반입니다(`max(5, 39 // 2)`). 반복의 빠르기는 모델에 따라 달라지므로, 반복이 절반으로 느려져도 울리게 했습니다.
- 같은 날의 운영 확인에서 사고의 반복이 1분에 42번 도구를 부르자 경보가 `ALARM`이 되었습니다. 알림은 사고 호출 86초 뒤에 왔습니다.
- 토큰 수와 CPU에는 경보를 걸지 않습니다. Amazon Bedrock 설명서에 따르면 토큰 수(`InputTokenCount`, `OutputTokenCount`)는 모델로만 나뉘는데, 허브의 에이전트는 같은 모델을 쓰므로 어느 에이전트인지 말하지 못합니다. AgentCore 안내서에 따르면 CPU 사용량(`CPUUsed-vCPUHours`)은 60분까지 늦을 수 있습니다. 둘 다 여기서 확인하지는 않았습니다.
- 평소의 1분 호출 수와, 다른 에이전트가 이 도구를 함께 쓸 때의 횟수는 재지 않았습니다.

## 무엇이 어디에 남는가

| 무엇 | 어디에 | 얼마나 두나 |
|---|---|---|
| 에이전트의 로그 | Runtime의 로그 그룹 `/aws/bedrock-agentcore/runtimes/<Runtime ID>-DEFAULT`. 세션마다 stream `runtime-logs-<세션 ID>`가 생깁니다 | AgentCore가 만들고, 허브는 보관 기간을 정하지 않습니다. 에이전트를 지울 때 함께 지웁니다 |
| 게이트웨이의 로그 | `/aws/vendedlogs/bedrock-agentcore/<prefix>-agents`, `/aws/vendedlogs/bedrock-agentcore/<prefix>-tools` | 이 모듈이 만들고 14일 둡니다 |
| 에이전트와 게이트웨이의 span | 계정의 CloudWatch Transaction Search가 받아 계정의 로그 그룹 `aws/spans`에 넣습니다 | 계정의 것이라 허브는 만들지도 지우지도 않습니다. `make destroy` 뒤에도 계정의 보관 기간(2026-11-22에 30일)까지 남습니다 |
| 메트릭 | 네임스페이스 `AWS/Bedrock-AgentCore` | AgentCore가 냅니다 |

- span이 `aws/spans`에 들어간 것은 2026-11-22에 Transaction Search가 켜진 계정에서 본 것입니다. 꺼진 계정에서는 해 보지 않았습니다.
- 같은 날 span은 호출이 끝나고 약 1분 뒤에, 에이전트의 호출 수는 2분 안에 보였습니다. CPU와 메모리는 2026-11-22에 읽은 AgentCore 개발자 안내서에 따르면 60분까지 늦을 수 있습니다.

## 에이전트의 trace

호스팅 심사의 배포 단계는 Runtime을 진입점 `["opentelemetry-instrument", "main.py"]`로 실행합니다. 팀의 `main.py`를 OpenTelemetry로 감싸 trace를 내게 합니다. `opentelemetry-instrument`는 ADOT 패키지 `aws-opentelemetry-distro`에 있고, 에이전트 템플릿과 이 저장소의 에이전트는 `requirements.txt`에서 이 패키지를 0.24.0으로 고정합니다. 에이전트의 실행 역할은 trace를 X-Ray로 보낼 수 있고, 메트릭은 namespace `bedrock-agentcore`에만 쓸 수 있습니다([호스팅 심사, 에이전트 실행 역할의 상한](../hosting_review/README.md#에이전트-실행-역할의-상한권한-경계)).

2026-11-22에 `release_review`를 에이전트 게이트웨이로 세 번 불러 본 것입니다.

- span은 계정의 로그 그룹 `aws/spans`에 들어갔습니다. 호출 하나에 span이 셋이었습니다(`POST /invocations`, `invoke_agent LangGraph`, `chat us.anthropic.claude-haiku-4-5-20251001-v1:0`).
- 세션 ID는 span의 `attributes.session.id`에 있습니다. 헤더 `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`로 보낸 값 그대로입니다.
- 에이전트 게이트웨이 로그 줄의 `trace_id`와 에이전트 span의 `traceId`가 같았습니다. 게이트웨이에서 에이전트까지 trace가 이어집니다.
- `chat` span에는 모델의 토큰 수(`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`)와 그 호출에 쓴 access key ID(`aws.auth.account.access_key`)가 있습니다. `aws/spans`를 읽을 수 있는 사람은 이 값들을 봅니다.
- Runtime의 로그 그룹에 생긴 stream `spans`는 비어 있었습니다. 안내서가 그 stream에 필요하다고 적는 `logs:PutResourcePolicy`가 허브의 실행 역할에 없는데, 그것이 까닭인지는 확인하지 않았습니다.
- 안내서가 호출마다 AgentCore가 낸다고 적는 span `AgentCore.Runtime.Invoke`는 호출 뒤 11분까지 보이지 않았습니다. namespace `bedrock-agentcore`에도 이 에이전트의 메트릭은 보이지 않았습니다.
- Omni와 CloudWatch의 GenAI Observability 화면으로 이 데이터를 보는 것은 확인하지 않았습니다.

## 게이트웨이의 로그와 trace

AgentCore는 게이트웨이의 로그를 보낼 곳을 스스로 만들지 않습니다. 그래서 이 모듈이 게이트웨이마다 CloudWatch Logs의 로그 전달 둘을 만듭니다. `<prefix>-agents-logs`와 `<prefix>-tools-logs`는 application 로그를 위의 로그 그룹 둘로 보내고, `<prefix>-agents-traces`와 `<prefix>-tools-traces`는 trace를 X-Ray로 보냅니다.

- 로그는 stream `BedrockAgentCoreGateway_ApplicationLogs`에 한 줄에 JSON 하나로 들어갑니다. 메시지는 `body.log`에 있습니다.
- 로그 전달이 로그 그룹에 쓰게 하는 자원 정책은 이 모듈의 `<prefix>-gateway-logs`입니다. 이 정책이 없으면 전달이 계정의 공유 정책에 문장을 더하고, `terraform destroy`는 그 문장을 지우지 않습니다.
- 2026-11-22의 `make destroy` 뒤에는 허브의 로그 전달과 로그 그룹이 남지 않았습니다. 계정의 다른 로그 전달과 자원 정책은 그대로였습니다.

## 사용량 보고

```bash
platform_team/agent_monitoring/usage.sh [minutes]      # minutes: 지난 몇 분(정수, 기본 60)
```

허브의 접두어와 리전은 `make`와 같은 규칙으로 리포의 `.env`에서 읽고, AWS에서는 읽기만 합니다. 표 둘을 출력합니다. 메트릭은 모두 네임스페이스 `AWS/Bedrock-AgentCore`에 있고, 창 안의 1분 값을 모두 더합니다. 값이 없는 메트릭은 0입니다.

| 표 | 한 줄 | 값(메트릭) |
|---|---|---|
| 에이전트 | 올라와 있는 에이전트 하나. Runtime `<prefix>_<에이전트>`로 찾고, harness 에이전트는 그 harness가 도는 Runtime `harness_<prefix>_<에이전트>`로 찾습니다 | 불린 수(`Invocations`), 새 세션 수(`Sessions`), 오류 수(`Errors`), vCPU-시간(`CPUUsed-vCPUHours`), GB-시간(`MemoryUsed-GBHours`) |
| 도구 | 카탈로그의 도구 하나 | 도구 게이트웨이로 불린 수(`Invocations`, `Method=tools/call`) |

2026-11-22에 `usage.sh 30`이 출력한 것입니다.

```
use of the hosted agents in the last 30 minutes (prefix hub, region us-west-2)
agent           invocations  sessions  errors  vCPU-hours  GB-hours
release_review            4         2       0    0.000000  0.000000

tool                           calls
Parts___get_part_spec              0
Parts___get_test_result            0
Quality___get_inspection_data      0
Release___file_review_request      0
Calls come in one-minute batches; CPU and memory may be up to 60 minutes late (AgentCore developer guide).
```

- 방금 부른 에이전트의 CPU와 메모리는 0으로 보일 수 있습니다. 위의 실행에서는 호출 뒤 11분에도 둘 다 0이었습니다.
- 관리자 자격 증명으로만 돌렸습니다. 플랫폼팀이 아닌 역할로는 돌려 보지 않았습니다.

Python에서 쓰는 함수는 셋입니다(`usage_report.py`).

| 함수 | 돌려주는 것 |
|---|---|
| `usage(c, s, p, minutes=60)` | 에이전트마다 `{"invocations", "sessions", "errors", "cpu_vcpu_hours", "memory_gb_hours"}` |
| `tool_calls(c, s, p, minutes=60)` | 도구(`<Target>___<도구>`)마다 불린 수 |
| `session_summary(c, s, agent, minutes=60)` | 그 에이전트의 세션마다 `{"session", "spans", "first", "last"}`. `aws/spans`의 span을 `attributes.session.id`로 셉니다 |

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | 알림 주제와 수신함, 도구 호출 경보, 게이트웨이 둘의 로그 그룹과 로그 전달, 자원 정책 |
| `usage_report.py`, `usage.sh` | 사용량 보고의 함수와 명령 |
| `agent_logs.py` | 에이전트의 Runtime 로그 그룹에서 가장 새 줄을 출력합니다(`demo_scenes/logs`). 개발팀 역할로 돌리면 harness 에이전트 `spec_assistant`의 로그 그룹은 거부를 한 줄로 출력합니다(2026-11-23) |
