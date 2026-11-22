# 모니터링

허브의 알림이 모이고, 올라온 에이전트가 무엇을 했는지 플랫폼팀이 보는 곳이다. SNS 주제 `<prefix>-alerts`를 두고, 확인용 SQS 수신함 `<prefix>-alerts-inbox`가 그 주제를 구독한다. `alert_email`을 주면 메일도 구독한다. 이 모듈은 알림 주제와 수신함, 도구 호출 알람(`<prefix>-tool-calls`), 그리고 두 게이트웨이의 로그와 trace 전달을 만든다. 이 주제로 알리는 알람은 둘이다. 이 모듈의 도구 호출 알람과, [커스텀 가드레일](../custom_guardrail/README.md)의 Terraform이 만드는 interceptor 오류 알람(`<prefix>-guardrail-errors`)이다. 사용량 보고(`usage.sh`)는 어느 에이전트가 몇 번 불렸고 어느 도구가 몇 번 불렸는지를 메트릭에서 읽어 표로 보여 준다.

## 개념도에서의 위치

"모니터링" 상자다. ⑩ "기록 수집"과 ⑪ "이상 탐지 알림"의 자리이다. ⑩으로는 게이트웨이 둘의 로그와 trace를 CloudWatch로 보내고, 사용량 보고가 메트릭을 읽는다. 에이전트의 trace는 호스팅 심사가 Runtime을 띄우는 방식(아래 "에이전트의 trace")에서 나온다. ⑪로는 알림 주제와 도구 호출 알람을 만든다. 호스팅 심사가 실패할 때(④-1 "심사 실패 알림")도 이 주제로 알린다.

## 도구 호출 알람

에이전트 하나가 같은 질문을 쉬지 않고 다시 묻는 사고를 플랫폼팀에 알린다. 그런 에이전트는 다시 물을 때마다 도구를 부르므로, 한 도구가 1분에 불리는 횟수가 평소보다 훨씬 많아진다. 알람은 알리기만 한다. 에이전트를 멈추는 것은 플랫폼팀의 명령이다([에이전트 멈추기와 재개](../agent_stop/README.md)).

| | |
|---|---|
| 보는 것 | 도구 게이트웨이가 도구마다 남기는 호출 수. 네임스페이스 `AWS/Bedrock-AgentCore`, 메트릭 `Invocations`, 차원 `Method=tools/call`, `Name=<지켜보는 도구>`, `Operation=InvokeGateway`, `Protocol=MCP`, `Resource=<도구 게이트웨이 ARN>` |
| 지켜보는 도구 | 변수 `watched_tool`. 기본값은 `Quality___get_inspection_data`(검사 건 조회) |
| 울리는 때 | 1분 합계(`Sum`, 1분 한 번으로 판단)가 변수 `tool_calls_per_minute`(기본값 19)보다 클 때 |
| 데이터가 없는 분 | 정상으로 본다(`notBreaching`). 아무도 그 도구를 부르지 않은 분이다 |
| 알리는 곳 | 알림 주제 `<prefix>-alerts` |

메트릭은 그 도구를 부른 모든 호출을 세고, 부른 에이전트를 나눠 세지 않는다. 이 리포의 에이전트 가운데 신청서(`agent.json`)에 이 도구를 적은 것은 `quality_agent` 하나다(에이전트 템플릿은 예시로 적어 둔다). 그래서 이 허브에서 알람이 울리면 `quality_agent`의 호출이다. 이것은 단위 시험(`tests/test_terraform_platform.py`)이 지킨다. 다른 에이전트에도 이 도구를 주면 알람은 그 에이전트의 호출도 함께 센다.

### 임계값을 정한 근거

2026-11-22의 두 실행에서, 사고의 되풀이(Strands로 만든 `quality_agent`에게 같은 질문을 쉬지 않고 다시 묻는 것, 모델은 Claude Haiku 4.5)는 루프 안에 온전히 든 1분 동안 도구를 47번과 39번 불렀다. 한 번 물을 때마다 도구 호출이 하나였다. 도구 게이트웨이의 `Invocations`(`Name=Quality___get_inspection_data`)도 같은 수를 보였고, 그 분이 끝나고 약 1분 뒤에 읽을 수 있었다([확인 시험](../../e2e_checks/spikes/README.md#결정)의 `LOOP_RATE`).

임계값 19는 낮은 쪽인 39의 절반이고, 5보다 작아지지 않게 했다(`max(5, 39 // 2)`). 되풀이의 빠르기는 모델이 답하는 빠르기에 달려 있으므로, 모델이나 때가 바뀌면 1분의 횟수도 바뀐다. 절반으로 둔 것은 되풀이가 그만큼 느려져도 울리게 하려는 것이다. 평소에는 질문 하나가 이 도구를 한두 번 부르므로, 사람이 묻는 1분은 임계값에 크게 못 미친다. 평소의 1분 호출 수는 재지 않았다.

### 토큰과 CPU에 알람을 걸지 않는 이유

- 토큰: Amazon Bedrock이 CloudWatch에 남기는 토큰 수(네임스페이스 `AWS/Bedrock`의 `InputTokenCount`, `OutputTokenCount`)는 모델(`ModelId`)로 나뉘고, 부른 쪽으로는 나뉘지 않는다(Amazon Bedrock 사용 설명서 "Monitor `bedrock-runtime` inference using CloudWatch metrics", 2026-11-22에 읽었다). 허브의 에이전트는 모두 같은 모델(`MODEL_ID`)을 부르므로, 이 수에 건 알람은 어느 에이전트가 쓰는지 말하지 못한다. 여기서는 확인하지 않았다.
- CPU: Runtime마다의 사용량 메트릭(`CPUUsed-vCPUHours`)은 있지만, AgentCore 개발자 안내서("AgentCore generated runtime observability data", 같은 날 읽었다)는 사용량 데이터가 60분까지 늦을 수 있다고 적는다. 1분 단위로 알아야 하는 사고에는 늦다. 여기서는 확인하지 않았다.

도구 호출 수는 되풀이 한 번에 하나씩 늘고, 그 분이 끝나고 약 1분 뒤에 읽혔다(위의 실행). 그래서 알람을 이 수에 건다.

### 확인한 것과 하지 않은 것

2026-11-22에 에이전트 없이 허브의 틀만 올렸다(`AUTO_APPROVE=1 make deploy`, 227초, `us-west-2`, 접두어 `hub`). 알람 `hub-tool-calls`가 만들어졌고, AWS가 돌려준 설정은 위의 표와 같았다(차원 다섯, `Sum`, 60초, 1번, `GreaterThanThreshold` 19, `notBreaching`, 알림 주제 `hub-alerts`). 상태는 알람이 만들어지고 93초 뒤에 `OK`가 되었고, 그 사유는 `no datapoints were received for 1 period and 1 missing datapoint was treated as [NonBreaching]`였다. 그 도구를 부른 호출이 없었으므로 데이터가 없는 분을 정상으로 본 것이다. 곧바로 `make deploy`를 한 번 더 돌리면 바뀐 것이 없었다(`0 added, 0 changed, 0 destroyed`). 그 뒤의 `AUTO_APPROVE=1 make destroy`(148초)는 마지막 줄이 `still present: nothing`이었고(`CloudWatch alarms: none`), 알람 `hub-tool-calls`가 남지 않은 것을 목록으로도 확인했다.

2026-11-22의 운영 확인(`make e2e-ops`, 같은 리전과 접두어)에서 사고 버전의 `quality_agent`에게 사건 질문을 한 번 보냈다(호출자는 20초 뒤에 포기했다). 되풀이는 온전히 든 두 분(22:11, 22:12 UTC)에 도구를 42번과 38번 불렀고, 이 알람의 메트릭도 그 두 분에 42와 38이었다. 알람은 22:12:17에 `OK`에서 `ALARM`이 되었고(`Threshold Crossed: 1 datapoint [42.0 (22/11/26 22:11:00)] was greater than the threshold (19.0).`), 그 알림이 알림 주제를 지나 호출 86초 뒤에 확인용 큐에 왔다. 에이전트를 멈춘 뒤 22:19:17에 다시 `OK`가 되었다.

확인하지 않은 것: 다른 에이전트가 이 도구를 함께 쓸 때의 횟수, 평소의 1분 호출 수.

## 무엇이 어디에 남는가

| 무엇 | 어디에 | 누가 만들고 얼마나 두나 |
|---|---|---|
| 에이전트의 로그 | Runtime의 로그 그룹 `/aws/bedrock-agentcore/runtimes/<Runtime ID>-DEFAULT`. 세션마다 stream `runtime-logs-<세션 ID>`, OpenTelemetry 로그 기록은 stream `otel-rt-logs`, Runtime이 뜰 때의 줄은 stream `build-logs-<UUID>` | AgentCore가 만든다. 허브는 보관 기간을 정하지 않고, 에이전트를 지울 때 함께 지운다. |
| 에이전트의 span | 계정의 CloudWatch Transaction Search가 받는다. 2026-11-22의 실행(Transaction Search가 켜져 있었다)에서는 계정의 로그 그룹 `aws/spans`에 들어갔다. Runtime의 로그 그룹에 생긴 stream `spans`는 비어 있었다. | 에이전트가 OpenTelemetry로 낸다(아래 "에이전트의 trace"). `aws/spans`와 Transaction Search는 계정의 것이라 허브는 만들지도, 지우지도, 설정을 바꾸지도 않는다. 그래서 `aws/spans`에 들어간 span은 `make destroy` 뒤에도 계정의 보관 기간(2026-11-22에 30일)까지 남는다. Transaction Search가 꺼진 계정에서는 해 보지 않았다. |
| 게이트웨이의 로그 | `/aws/vendedlogs/bedrock-agentcore/<prefix>-agents`, `/aws/vendedlogs/bedrock-agentcore/<prefix>-tools`. 2026-11-22의 실행에서 에이전트 게이트웨이의 줄은 stream `BedrockAgentCoreGateway_ApplicationLogs`에 있었다. 같은 날의 운영 확인에서 도구 게이트웨이의 줄도 같은 이름의 stream에 있었다(아래 "게이트웨이의 로그와 trace"). | 이 모듈의 로그 전달(아래 "게이트웨이의 로그와 trace"). 14일 둔다. |
| 게이트웨이의 span | X-Ray로 보낸다. 2026-11-22의 실행(Transaction Search가 켜져 있었다)에서는 에이전트 게이트웨이의 span이 `aws/spans`에 들어갔다. 같은 날의 운영 확인에서 도구 게이트웨이의 span도 `aws/spans`에 있었다. | 이 모듈의 trace 전달(X-Ray). Transaction Search가 꺼진 계정에서는 해 보지 않았다. |
| 메트릭 | 네임스페이스 `AWS/Bedrock-AgentCore` | AgentCore가 낸다(아래 표). |

사용량 보고가 읽는 메트릭이다. 이름과 차원은 2026-11-22에 이 계정의 메트릭 목록에서 본 것이다. 같은 메트릭이 차원 `ComputeType=MicroVM`을 더한 모양으로도 있었다. 사용량 보고는 그것을 읽지 않는다.

| 무엇을 세나 | 메트릭 | 차원 |
|---|---|---|
| 에이전트(Runtime의 endpoint `DEFAULT`)가 불린 수, 새로 생긴 세션 수, 오류 수 | `Invocations`, `Sessions`, `Errors` | `Name=<Runtime 이름>::DEFAULT`, `Operation=InvokeAgentRuntime`, `Resource=<Runtime ARN>` |
| Runtime이 쓴 CPU와 메모리 | `CPUUsed-vCPUHours`, `MemoryUsed-GBHours` | `Name=<Runtime 이름>::DEFAULT`, `Resource=<Runtime ARN>`, `Service=AgentCore.Runtime` |
| 도구가 불린 수(부른 쪽을 가리지 않는다) | `Invocations` | `Method=tools/call`, `Name=<Target>___<도구>`, `Operation=InvokeGateway`, `Protocol=MCP`, `Resource=<도구 게이트웨이 ARN>` |

## 에이전트의 trace

호스팅 심사의 배포 단계는 Runtime을 진입점 `["opentelemetry-instrument", "main.py"]`로 띄운다. 팀의 `main.py`를 OpenTelemetry로 감싸 띄우는 것이고, AWS 문서가 코드 배포에 쓰는 방식이다(AgentCore 개발자 안내서 "Direct code deployment for Python", 2026-11-22에 읽었다). `opentelemetry-instrument`는 ADOT 패키지 `aws-opentelemetry-distro`에 들어 있다. 에이전트 템플릿과 두 에이전트의 `requirements.txt`가 이 패키지를 0.24.0(2026-11-22에 PyPI의 최신)으로 고정한다. 에이전트의 실행 역할은 trace를 X-Ray로 보낼 수 있고, 메트릭은 namespace `bedrock-agentcore`에만 쓸 수 있다([호스팅 심사, 에이전트 실행 역할의 상한](../hosting_review/README.md#에이전트-실행-역할의-상한권한-경계)).

2026-11-22의 실행(`us-west-2`, 접두어 `hub`, 계정의 Transaction Search는 켜져 있었다)에서 `release_review` 하나를 올리고, 심사가 끝난 뒤 에이전트 게이트웨이로 세 번 불렀다(세 번 모두 세션 ID 헤더에 같은 값을 실었다). 본 것은 다음과 같다.

- 패키지를 더한 뒤에도 심사가 `SUCCEEDED`였다(381초). 검사의 `pip-audit`(2.10.1)는 `No known vulnerabilities found`였고, 배포의 코드 묶음은 41,466,931바이트였다(패키지를 더하기 전에는 약 31 MB). 새 Runtime은 231초 뒤에 `READY`였고, 심사의 시험 호출과 세 호출이 모두 200이었다. 감싼 진입점으로도 에이전트가 떴다.
- span은 계정의 로그 그룹 `aws/spans`에 들어갔고, 세 호출이 끝나고 약 1분 뒤에 보였다. 호출 하나에 span이 셋이었다. `POST /invocations`(Starlette 계측), `invoke_agent LangGraph`(ADOT의 LangChain 계측), `chat us.anthropic.claude-haiku-4-5-20251001-v1:0`(botocore의 bedrock-runtime 계측)이다.
- span 한 줄은 JSON이다. 맨 위의 필드는 `attributes`, `durationNano`, `endTimeUnixNano`, `flags`, `kind`, `name`, `parentSpanId`, `resource`, `scope`, `spanId`, `startTimeUnixNano`, `status`, `traceId`였다. 세션 ID는 `attributes.session.id`에 있었다. 헤더 `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`로 보낸 값 그대로였고, 헤더 없이 부른 심사의 시험 호출은 UUID였다. `resource.attributes`에는 Runtime ID가 든 `cloud.resource_id`(endpoint ARN)와 `aws.log.group.names`가 있었다. `chat` span의 `attributes`에는 모델의 입력과 출력 토큰 수(`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`)와, 그 호출에 쓴 자격 증명의 access key ID(`aws.auth.account.access_key`)가 있었다. `aws/spans`를 읽을 수 있는 사람은 이 값들을 본다.
- Runtime의 로그 그룹에도 stream `spans`가 생겼지만 비어 있었다. AgentCore 개발자 안내서("Add observability to your Amazon Bedrock AgentCore resources", 2026-11-22에 읽었다)는 지원하는 리전에서 새로 만든 에이전트의 span이 이 stream으로 가고, 그러려면 실행 역할이 그 로그 그룹에 `logs:PutResourcePolicy`를 가져야 한다고 적는다. 허브의 실행 역할에는 그 권한이 없다(위의 링크에 이유가 있다). 이 실행의 span이 `aws/spans`로 간 까닭이 그것인지는 확인하지 않았다.
- 이 실행에서 Runtime의 로그 그룹에 있던 stream은 `build-logs-<UUID>`(Runtime이 뜰 때의 줄 4개), `otel-rt-logs`(OpenTelemetry 로그 기록 24줄, 줄마다 `traceId`와 `spanId`), 세션마다의 `runtime-logs-<세션 ID>`, 그리고 비어 있던 `spans`였다. `runtime-logs-…`의 줄에는 `trace_id=…`, `span_id=…`가 붙어 있었다. 감싸지 않은 Runtime을 본 같은 날의 앞선 실행은 그룹의 stream을 모두 적지 않았다(이름 순서로 마지막 여섯, `runtime-logs-…`와 `spans`만 적었다). 그래서 이 가운데 어느 stream이 감싼 진입점 때문에 생기는지는 확인되지 않았다. 실행 역할이 거부된 줄이나 오류 줄은 없었다.
- 세 번째 호출의 에이전트 게이트웨이 로그 줄의 `trace_id`와 에이전트 span의 `traceId`가 같았다. 게이트웨이에서 에이전트까지 trace가 이어진다.
- 안내서("AgentCore generated runtime observability data", 2026-11-22에 읽었다)가 호출마다 AgentCore가 낸다고 적는 span `AgentCore.Runtime.Invoke`(operation `InvokeAgentRuntime`)는 호출 뒤 11분(19:22 UTC)까지 `aws/spans`에도 Runtime의 stream `spans`에도 보이지 않았다.
- 실행 역할은 namespace `bedrock-agentcore`에 메트릭을 보낼 수 있지만, 이 실행에서 이 에이전트의 메트릭은 그 namespace에 보이지 않았다. 그 namespace의 `gen_ai.client.token.usage`와 `http.server.duration`에 18:30부터 19:25(UTC)까지 값이 하나도 없었다. 그 namespace에 있던 메트릭에는 에이전트를 가리키는 차원이 없고, 계정의 다른 에이전트도 그 namespace에 쓴다.

## 게이트웨이의 로그와 trace

AgentCore는 게이트웨이의 로그를 보낼 곳을 스스로 만들지 않는다(AgentCore 개발자 안내서 "Add observability to your Amazon Bedrock AgentCore resources", 2026-11-22에 읽었다). 그래서 이 모듈이 게이트웨이마다 CloudWatch Logs의 로그 전달 둘을 만든다. 전달 하나는 게이트웨이에 둔 source, 보낼 곳(destination), 그 둘을 잇는 delivery다. 하나는 application 로그(`APPLICATION_LOGS`)를 로그 그룹 `/aws/vendedlogs/bedrock-agentcore/<prefix>-agents`(에이전트 게이트웨이)와 `…/<prefix>-tools`(도구 게이트웨이)로 보내고, 다른 하나는 trace(`TRACES`)를 X-Ray로 보낸다. 이름은 source와 destination 모두 `<prefix>-agents-logs`, `<prefix>-agents-traces`, `<prefix>-tools-logs`, `<prefix>-tools-traces`다. 로그 전달이 로그 그룹에 쓰려면 `delivery.logs.amazonaws.com`이 그 그룹에 쓸 수 있게 하는 자원 정책이 있어야 한다. 이 모듈의 정책 `<prefix>-gateway-logs`가 그것이다. 그런 정책이 없으면 전달이 계정의 공유 정책에 문장을 더하고, 그 문장은 `terraform destroy`가 지우지 않는다(호스팅 심사의 state machine 로그도 같은 까닭으로 자기 정책을 둔다).

2026-11-22의 실행에서 본 것은 다음과 같다.

- `make deploy`가 source 넷(`APPLICATION_LOGS` 둘, `TRACES` 둘), destination 넷(`CWL` 둘, `XRAY` 둘), delivery 넷과 정책 `hub-gateway-logs`를 만들었다. 계정에 있던 자원 정책(로그 전달이 함께 쓰는 공유 정책을 포함해서)의 마지막 수정 시각은 그대로였다. 곧바로 `make deploy`를 한 번 더 돌리면 바뀐 것이 없었다(`0 added, 0 changed, 0 destroyed`).
- 두 로그 그룹 모두에 AWS가 만든 stream `log_stream_created_by_aws_to_validate_log_delivery_subscriptions`(한 줄)가 생겼다.
- 에이전트 게이트웨이의 로그 그룹에는 stream `BedrockAgentCoreGateway_ApplicationLogs`에 15줄이 있었다(심사의 시험 호출과 세 호출의 때). 읽은 것은 처음 두 줄과 마지막 줄이고, 그 메시지(`body.log`)는 `Started processing InvokeHttpGateway request`, `Executing Http request for target <target ID> - RequestId: <요청 ID>`, `Successfully processed InvokeHttp request`였다. 한 줄은 JSON이고 필드는 `account_id`, `attributes`, `body`(`log`, `isError`, `id`), `event_timestamp`, `request_id`, `resource`, `resource_arn`, `severityNumber`, `severityText`, `spanId`, `span_id`, `timeUnixNano`, `traceId`, `trace_id`였다.
- 도구 게이트웨이의 로그 그룹에는 확인용 stream 하나뿐이었다. 이 실행에서는 도구를 부른 호출이 없었다(`release_review`의 답이 `tools_used: []`였다). 그래서 도구 게이트웨이의 로그 줄은 보지 못했다.
- 같은 날의 운영 확인(`make e2e-ops`, 도구를 부르는 에이전트 넷)에서는 도구 게이트웨이의 로그 그룹 `/aws/vendedlogs/bedrock-agentcore/hub-tools`의 stream `BedrockAgentCoreGateway_ApplicationLogs`에 35분 동안 줄 494개가 들어왔다. 메시지(`body.log`)는 `Started processing request` 103, `Received request for tools/call method` 94, `Policy evaluation completed` 94, `Executing tool Quality___get_inspection_data from <target>` 85, `Executing tool Parts___get_part_spec from <target>` 8, `Executing tool Release___file_review_request from <target>` 1, `Successfully processed request` 100, 그리고 `initialize`, `notifications/initialized`, `tools/list` 요청이 셋씩이었다. 도구 게이트웨이의 span도 `aws/spans`에 있었다. 이름은 `AgentCore.Gateway.InboundAuth`, `AgentCore.Gateway.AuthorizeRequest`, `AgentCore.Gateway.EvaluateRoutingRules`, `AgentCore.Policy.AuthorizeAction`, `AgentCore.Gateway.InvokeTool`과 도구마다의 `AgentCore.Gateway.InvokeTool.<Target>___<도구>`, `AgentCore.Gateway.TargetInvocation`이었다. 허브의 에이전트는 `tools/call`만 부르고 그 시간에 harness를 세 번 불렀는데, `tools/list`도 셋이었고 `AgentCore.Gateway.ListTools`와 `AgentCore.Policy.PartiallyAuthorizeActions`의 span도 셋씩이었다. 이 둘이 무엇을 거르는지는 확인하지 않았다.
- 에이전트 게이트웨이의 span이 `aws/spans`에 들어갔다. 이름은 `AgentCore.Gateway.InboundAuth`, `AgentCore.Gateway.AuthorizeRequest`, `AgentCore.Gateway.EvaluateRoutingRules`, `AgentCore.Policy.AuthorizeAction`, `AgentCore.Gateway.TargetInvocation`, `AgentCore.Gateway.InvokeHttp`, `AgentCore.Gateway.Http.ReleaseReview`였다.
- 그 뒤의 `AUTO_APPROVE=1 make destroy`(380초)는 마지막 줄이 `still present: nothing`이었다(`log delivery sources: none`, `log delivery destinations: none`, `log deliveries: none`, `log groups: none`). 허브의 source, destination, delivery와 `/aws/vendedlogs/bedrock-agentcore/hub-…` 로그 그룹이 남지 않은 것을 목록으로도 확인했다. 계정에 있던 다른 로그 전달과 자원 정책의 수는 그대로였고, Transaction Search의 설정과 `aws/spans`의 보관 기간도 그대로였다.

## 늦게 보이는 것

- 에이전트의 span: 2026-11-22의 실행에서 호출이 끝나고 약 1분 뒤에 `aws/spans`에서 보였다.
- 에이전트가 불린 수(`Invocations`, `Sessions`): 같은 실행에서 호출(19:11:12~14 UTC)이 끝나고 2분 안에(19:13:18) 읽혔다. AgentCore 개발자 안내서("AgentCore generated runtime observability data", 2026-11-22에 읽었다)는 Runtime의 메트릭이 1분 단위로 모여 온다고 적는다.
- CPU와 메모리(`CPUUsed-vCPUHours`, `MemoryUsed-GBHours`): 같은 안내서는 사용량 데이터가 60분까지 늦을 수 있다고 적는다. 같은 실행에서 사용량 보고는 호출 뒤 11분(19:22)에도 둘 다 0을 보였다. 19:30에 같은 차원으로 읽자 19:10부터 19:13까지의 1분 값이 있었다(합 0.004023 vCPU-시간, 0.139626 GB-시간). 그 사이 언제 들어왔는지는 보지 않았다.

## 사용량 보고

```bash
platform_team/agent_monitoring/usage.sh [minutes]      # minutes: 지난 몇 분(정수, 기본 60)
```

허브의 접두어와 리전은 `make`와 같은 규칙으로 리포의 `.env`에서 읽는다. 읽기만 한다. 표 둘을 찍는다. 첫째는 올라와 있는 에이전트(이름이 `<prefix>_<에이전트>`인 Runtime. harness 에이전트는 AgentCore가 그 harness를 돌리는 Runtime `harness_<prefix>_<에이전트>`로 찾고, 그 Runtime의 이름으로 메트릭을 읽는다)마다 불린 수, 새 세션 수, 오류 수, vCPU-시간, GB-시간이다. 둘째는 카탈로그의 도구마다 도구 게이트웨이로 불린 수다. 메트릭마다 그 창 안의 1분 값을 모두 더한다. 값이 없는 메트릭은 0이다.

2026-11-22의 실행에서 `usage.sh 30`(19:13:18)은 아래와 같았다. 세 호출에 더해 30분 안에 있던 심사의 시험 호출(호출 하나, 세션 하나)까지 셌으므로 4와 2다. 1분 값은 19:10에 1, 19:11에 3이었다. 그 직후의 `usage.sh 2`는 `release_review 3 1 0`이었다.

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

Python에서 쓰는 함수는 셋이다(`usage_report.py`).

| 함수 | 돌려주는 것 |
|---|---|
| `usage(c, s, p, minutes=60)` | 에이전트마다 `{"invocations", "sessions", "errors", "cpu_vcpu_hours", "memory_gb_hours"}` |
| `tool_calls(c, s, p, minutes=60)` | 도구(`<Target>___<도구>`)마다 불린 수 |
| `session_summary(c, s, agent, minutes=60)` | 그 에이전트의 세션마다 `{"session", "spans", "first", "last"}`, span이 많은 것부터. Logs Insights로 `aws/spans`에서 Runtime ID가 든 줄과, Runtime의 로그 그룹의 stream `spans`를 읽고 `attributes.session.id`로 센다. |

같은 실행에서 `session_summary(c, s, "release_review", 30)`은 세션 둘을 돌려주었다. 헤더로 보낸 세션이 span 9개(19:11:12.312부터 19:11:14.175까지), 시험 호출의 세션이 span 3개였다. Runtime의 stream `spans`를 읽는 길은 그 stream이 비어 있었으므로 확인되지 않았다.

같은 날의 운영 확인에서 `usage.sh 60`(22:20 UTC 무렵)은 에이전트 넷을 보였다. `docs_adk` 2번(세션 2), `quality_agent` 8번(세션 7, 오류 1. 멈춘 사고의 호출이다), `release_review` 6번(세션 6), `spec_assistant` 3번(세션 3)이었다. `quality_agent`와 `release_review`의 CPU와 메모리(0.046634와 0.036542 vCPU-시간, 2.137044와 1.960158 GB-시간)는 그 한 시간 안에 이미 값이 있었다. `spec_assistant`는 둘 다 0이었다. 도구 표는 `Quality___get_inspection_data` 85, `Parts___get_part_spec` 9, `Parts___get_test_result` 1, `Release___file_review_request` 2였다. `spec_assistant`의 줄은 harness가 도는 Runtime(`harness_hub_spec_assistant`)의 메트릭이다. 그 Runtime의 메트릭 목록(차원 `Resource=<Runtime ARN>`)에는 `Invocations`, `Sessions`, `Errors`, `Duration`, `Latency`, `Throttles`, `SystemErrors`, `UserErrors`가 `Name=harness_hub_spec_assistant::DEFAULT`, `Operation=InvokeAgentRuntime`으로 있었다(같은 메트릭이 `ComputeType=MicroVM`을 더한 모양과, `EndpointQualifier=DEFAULT`와 `HarnessId=<harness ARN>`을 더한 모양으로도 있었다). `CPUUsed-vCPUHours`와 `MemoryUsed-GBHours`는 그때 목록에 없었다. 같은 허브에서 다시 돌린 두 번째 실행의 `usage.sh 60`(22:42 UTC 무렵)에서는 `spec_assistant`의 줄에 CPU와 메모리도 있었다(6번, 0.028382 vCPU-시간, 1.744684 GB-시간). 사용량 보고가 읽는 차원(`Name`, `Resource`, `Service=AgentCore.Runtime`)으로 그 Runtime의 값이 읽힌 것이다.

## 확인하지 않은 것(관측)

- 도구 게이트웨이의 로그 줄과 span, 도구 표에 0이 아닌 값, `quality_agent`(Strands)의 span은 같은 날의 운영 확인에서 봤다(위와 아래 "사용량 보고"). `quality_agent`의 span은 `aws/spans`에 있었고, `session_summary`가 세션 여덟을 찾았다(되풀이하던 사고의 세션 하나에 span 729개, 22:10:58부터 22:12:51까지).
- Omni와 CloudWatch의 GenAI Observability 화면으로 이 데이터를 보는 것.
- 사용량 보고를 플랫폼팀이 아닌 역할로 돌리는 것. 실행에서는 관리자 자격 증명으로 돌렸다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | SNS 주제, SQS 수신함과 그 접근 정책, 구독(SQS, 고르면 메일), 도구 호출 알람 `<prefix>-tool-calls`, 게이트웨이 둘의 로그 그룹과 로그 전달(source, destination, delivery), 그 전달을 위한 자원 정책 `<prefix>-gateway-logs`. 입력은 `prefix`, `alert_email`, `tool_gateway_arn`, `agent_gateway_arn`, `watched_tool`, `tool_calls_per_minute`. 내보내는 값은 `topic_arn`, `tool_alarm_name`. |
| `usage_report.py` | 사용량 보고(`usage`, `tool_calls`, `session_summary`)와 그 명령. 메트릭과 span을 읽기만 한다. |
| `usage.sh` | 사용량 보고 명령. `.env`를 `make`와 같은 규칙으로 읽고 `usage_report.py`를 돌린다. |
