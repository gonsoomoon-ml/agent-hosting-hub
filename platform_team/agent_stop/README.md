# 에이전트 멈추기와 재개

호스팅된 에이전트 하나가 이상하게 돌 때(예를 들어 쉬지 않고 도구를 부를 때) 플랫폼팀은 그 에이전트만 멈춥니다. 팀이 고친 버전이 심사를 지나면 다시 엽니다. 다른 에이전트는 건드리지 않습니다.

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 ⑫ "전사 정책 설정, 이상 에이전트 차단"의 "이상 에이전트 차단"입니다. "에이전트 게이트웨이" 상자의 진입에 정책을 하나 걸고, 그 에이전트의 Runtime에서 도는 세션을 끝냅니다.

## 명령 둘

```
platform_team/agent_stop/stop.sh <에이전트> [--session <세션 ID> ...]   # 멈춥니다
platform_team/agent_stop/resume.sh <에이전트>                         # 다시 엽니다
```

- 플랫폼팀의 자격 증명으로 돕니다. 허브의 접두어와 리전은 `.env`에서 읽습니다([시작하기의 `.env`](../../docs/getting-started.md#env)).
- 인자가 맞지 않으면 사용법을 출력하고 아무것도 바꾸지 않습니다. 실패하면 이유를 한 줄로 출력하고 0이 아닌 값으로 끝납니다.
- 에이전트 게이트웨이에 그 에이전트의 진입 target이 없으면 거부합니다. SSM `/<prefix>/agents/<에이전트>/runtime_arn`의 값이 그 에이전트의 Runtime ARN이 아닐 때도 거부합니다.

## 멈춤이 하는 일과 순서

`stop.sh`는 세션을 끝내는 사이에 새 세션이 열리지 않도록 진입부터 막습니다.

1. 진입을 막습니다. 에이전트 게이트웨이에 아래의 Cedar forbid `stop_agent_<에이전트>`를 겁니다.
2. 세션을 끝냅니다. 세션마다 `StopRuntimeSession`을 부릅니다.

```text
forbid (principal, action == AgentCore::Action::"<Target>___POST:/invocations", resource == AgentCore::Gateway::"<에이전트 게이트웨이 ARN>") unless { principal == AgentCore::IamEntity::"arn:aws:sts::<ACCOUNT>:assumed-role/<prefix>-review-testcall-role" };
```

- 심사의 시험 호출 역할만 forbid에서 빠집니다. 멈춘 동안에도 고친 버전의 심사는 에이전트를 부를 수 있습니다.
- 정책이 `ACTIVE`가 되기를 300초까지 기다립니다. 되지 않으면 정책을 지우고, 세션은 하나도 끝내지 않습니다.
- 끝내지 못한 세션이 하나라도 있으면 0이 아닌 값으로 끝납니다. 멈춤 정책은 그대로 둡니다.
- 같은 명령을 두 번 돌리면 정책은 하나로 남고, 그때 찾은 세션을 다시 끝냅니다.

`resume.sh`는 멈춤 정책을 지우고 사라질 때까지 기다립니다. 멈춘 에이전트가 아니면 `was not stopped: nothing changed`를 출력합니다.

## 멈춘 동안 보이는 것

2026-11-22의 실행에서 본 것입니다([확인한 것](../../docs/checks.md#make-e2e-ops가-확인하는-것)).

| 무엇 | 보인 것 |
|---|---|
| `stop.sh` | 17~20초 걸렸습니다. |
| 사용자의 호출 | 403이었고, 본문이 정책의 이름 `stop_agent_<에이전트>`를 담았습니다. |
| 돌던 요청 | 세션을 끝낸 뒤 10~16초 사이에 멎었고, 호출자는 HTTP 500을 받았습니다. 이 줄은 `make e2e-ops`가 아니라 같은 날의 확인 테스트에서 본 것입니다. |
| 고친 버전의 심사 | 멈춘 채로 제출하자 `SUCCEEDED`였습니다. |
| 다른 에이전트 | 그동안 답했습니다. |
| `resume.sh` | 8초 걸렸고, 끝난 뒤 첫 호출부터 200이었습니다. |

고친 버전이 승인되어도 사용자의 호출은 403입니다. 멈춤 정책은 `resume.sh`를 돌릴 때까지 남습니다.

## 멈춤과 재개가 바꾸지 않는 것

- 진입 permit(`entry_permit_<에이전트>`), 도구 permit, guard, 전사 정책, Runtime은 그대로입니다.
- 반려는 멈춤 정책을 보지 않고, 멈추기 전과 같은 일을 합니다.
- 반려와 `make destroy`가 에이전트의 것을 지울 때는 멈춤 정책도 지웁니다([호스팅 심사, 지우는 것과 순서](../hosting_review/README.md#지우는-것과-순서)).

## 세션을 어디서 찾나

`--session`을 주면 그 세션만 끝냅니다. 주지 않으면 Runtime의 로그 그룹 `/aws/bedrock-agentcore/runtimes/<Runtime ID>-DEFAULT`에서 이름이 `runtime-logs-`로 시작하는 log stream을 찾습니다. 그 뒤의 글자가 세션 ID입니다.

- 지난 30분 안에 생겼거나 갱신된 stream만 봅니다. 그보다 오래 도는 세션은 `--session <ID>`로 줍니다.
- 세션 헤더 `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` 없이 부른 호출도 세션이 되므로 끝냅니다.
- stream 목록은 어느 세션이 아직 도는지 말해 주지 않습니다. 이미 끝난 세션은 `already ended`로 출력하고 실패로 세지 않습니다(2026-11-22에 찾은 여덟 가운데 여섯).
- `--session`으로 준 ID가 33~256자가 아니면 보내지 않고, 끝내지 못한 것으로 출력합니다.

## 한계

- 게이트웨이의 진입만 막고, Runtime을 직접 부르는 길은 남습니다. 이 허브를 만들기 전 2026-11-21의 확인 실행에서, 진입에 forbid가 걸린 동안 Runtime을 직접 부르자 200이었습니다.
- harness 에이전트는 진입 target이 없어 멈출 수 없습니다. `stop.sh`가 거부합니다.
- 30분보다 오래 도는 세션은 찾지 못할 수 있고, AWS에서 해 보지 않았습니다. 세션을 연 뒤 stream이 얼마 만에 생기는지도 확인하지 않았습니다(2026-11-22에는 연 지 30초에 있었습니다).
- 심사의 시험 호출이 연 세션도 지난 30분 안의 것이면 끝냅니다.
- 명령이 부르는 API는 `ListGatewayTargets`, `GetParameter`, `ListPolicies`, `CreatePolicy`, `GetPolicy`, `UpdatePolicy`, `DeletePolicy`, `DescribeLogStreams`, `StopRuntimeSession`입니다. 필요한 IAM 권한은 확인하지 않았고, 관리자 권한으로만 돌렸습니다.
- AWS에서 해 보지 않은 것: Runtime의 resource-based policy로 직접 호출을 막는 것, 한 번도 없던 세션 ID에 `StopRuntimeSession`.

## 파일

| 파일 | 역할 |
|---|---|
| `stop_agent.py` | 멈추기, 재개, SSM의 Runtime ARN 확인, 최근 세션 찾기 |
| `stop.sh`, `resume.sh` | 위의 명령 둘. 리포의 `.env`를 읽고 `stop_agent`를 부릅니다. |
