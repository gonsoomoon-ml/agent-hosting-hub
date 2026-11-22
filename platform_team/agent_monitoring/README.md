# 모니터링

허브의 알림이 모이는 곳이다. SNS 주제 `<prefix>-alerts`를 두고, 확인용 SQS 수신함 `<prefix>-alerts-inbox`가 그 주제를 구독한다. `alert_email`을 주면 메일도 구독한다. 이 모듈은 알림 주제와 수신함, 그리고 도구 호출 알람(`<prefix>-tool-calls`)을 만든다. 이 주제로 알리는 알람은 둘이다. 이 모듈의 도구 호출 알람과, [커스텀 가드레일](../custom_guardrail/README.md)의 Terraform이 만드는 interceptor 오류 알람(`<prefix>-guardrail-errors`)이다.

## 개념도에서의 위치

"모니터링" 상자다. ⑩ "기록 수집"과 ⑪ "이상 탐지 알림"의 자리이고, 지금은 ⑪의 알림 주제와 도구 호출 알람을 만든다. 호스팅 심사가 실패할 때(④-1 "심사 실패 알림")도 이 주제로 알린다.

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

확인하지 않은 것: 되풀이가 이 알람을 울리는 것과, 되풀이가 시작되고 알림이 오기까지의 시간. 다른 에이전트가 이 도구를 함께 쓸 때의 횟수.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | SNS 주제, SQS 수신함과 그 접근 정책, 구독(SQS, 고르면 메일), 도구 호출 알람 `<prefix>-tool-calls`. 입력은 `prefix`, `alert_email`, `tool_gateway_arn`, `watched_tool`, `tool_calls_per_minute`. 내보내는 값은 `topic_arn`, `tool_alarm_name`. |
