# 에이전트 멈추기와 재개

호스팅된 에이전트 하나가 이상하게 돌 때(예를 들어 쉬지 않고 도구를 부를 때) 플랫폼팀은 그 에이전트만 멈춘다. 팀이 고친 버전을 올려 심사를 지나면 다시 연다. 다른 에이전트는 건드리지 않는다. 멈춤은 운영 중에 API로 거는 정책 하나와 API 호출이라서 이 폴더에는 Terraform 모듈이 없다.

## 개념도에서의 위치

⑫ "전사 정책 설정, 이상 에이전트 차단"의 "이상 에이전트 차단"이다. "에이전트 게이트웨이" 상자의 진입에 정책을 하나 걸고, 그 에이전트의 Runtime에서 도는 세션을 끝낸다.

## 명령 둘

```
platform_team/agent_stop/stop.sh <에이전트> [--session <세션 ID> ...]   # 멈춘다
platform_team/agent_stop/resume.sh <에이전트>                         # 다시 연다
```

어느 폴더에서 불러도 된다. 허브의 접두어와 리전은 `make`와 같은 규칙으로 리포의 `.env`에서 읽는다([README의 `.env`](../../README.md#env)). 첫 줄에 어느 허브인지(접두어, 리전) 찍는다. 플랫폼팀의 자격 증명으로 돈다. 인자가 맞지 않으면 사용법을 찍고 아무것도 바꾸지 않는다. 실패하면 이유를 한 줄로 찍고(계정 ID는 `<ACCOUNT>`로 가린다) 0이 아닌 값으로 끝난다.

이 문서가 적는 두 명령의 동작은 코드와 단위 시험(`tests/test_agent_stop.py`, `tests/test_aws_calls.py`)이 정한 것이다. AWS에서 본 것으로 적은 것은 2026-11-22의 확인 시험(`e2e_checks/spikes/spike_operations.py`, 두 번)이 같은 정책 문장과 같은 호출로 본 것과, 같은 날 운영 확인(`make e2e-ops`)이 두 명령을 돌려 본 것이다([확인 시험](../../e2e_checks/spikes/README.md), 아래 "운영 확인에서 본 것").

## 멈춤이 하는 일과 순서

`stop.sh`는 두 가지를 이 순서로 한다.

1. 진입을 막는다. 에이전트 게이트웨이에 정책 `stop_agent_<에이전트>`를 건다. 그 에이전트의 진입(`<Target>___POST:/invocations`)을 거부하는 Cedar forbid이고, 심사의 시험 호출 역할만 예외다. 적용 모드 `ACTIVE`, 검증 `IGNORE_ALL_FINDINGS`로 만들고, 정책의 상태가 `ACTIVE`가 될 때까지 기다린다(300초까지). `ACTIVE`가 되지 않으면 만들다 만 정책을 지우고 멈춘다. 그때는 세션을 하나도 끝내지 않는다.

   ```text
   forbid (principal, action == AgentCore::Action::"<Target>___POST:/invocations", resource == AgentCore::Gateway::"<에이전트 게이트웨이 ARN>") unless { principal == AgentCore::IamEntity::"arn:aws:sts::<ACCOUNT>:assumed-role/<prefix>-review-testcall-role" };
   ```

2. 세션을 끝낸다. 세션마다 `StopRuntimeSession`(`runtimeSessionId`, `agentRuntimeArn`, `qualifier` `DEFAULT`)을 부른다. `StopRuntimeSession`이 찾지 못하는 세션(`ResourceNotFoundException`)은 이미 끝난 것이므로 `session <ID>: already ended (<이유>)`로 찍고 실패로 세지 않는다(아래 "세션을 어디서 찾나"). 그 밖의 이유로 끝내지 못한 세션은 이유와 함께 한 줄(`session <ID>: not stopped (<이유>)`)로 찍고 다음 세션으로 넘어간다. 그런 세션이 하나라도 있으면 명령은 0이 아닌 값으로 끝난다. 만든 멈춤 정책은 그때도 지우지 않는다.

진입을 먼저 막는 이유: 세션을 먼저 끝내면, 끝내는 사이에 사용자의 새 호출이 새 세션을 열 수 있다(헤더 없는 호출도 세션이 되었다. 아래 "세션을 어디서 찾나"의 2026-11-22 관찰). 그래서 진입을 먼저 막는다. 세션은 정책이 `ACTIVE`가 된 뒤에 찾으므로, 그때 stream이 있는 세션은 막기 직전에 열린 것이라도 목록에 든다. 세션을 연 뒤 stream이 얼마 만에 생기는지는 확인하지 않았다(2026-11-22에 요청을 연 지 30초에는 있었다).

멈춤은 에이전트의 도구 permit을 지우지 않는다. 아래의 관찰처럼 세션을 끝내면 돌던 일이 멎었기 때문이다.

2026-11-22의 확인 시험에서 본 것(두 번):

- 같은 문장의 정책 `stop_agent_quality_agent`가 13초 만에 `ACTIVE`가 되었고, 그 뒤 사용자의 첫 호출부터 403이었다. 본문이 정책의 이름을 담는다: `Request Denied: Gateway Target request not allowed due to policy enforcement [Policy evaluation denied due to stop_agent_quality_agent-<10자>]`. 확인 시험은 두 에이전트가 승인된 허브(`make deploy seed e2e` 뒤)에서 돌았고, 승인은 사용자를 들이는 `entry_permit_<에이전트>`를 건다. 그런 에이전트를 forbid가 거부한 것이다. 정책을 지운 뒤 사용자의 호출은 다시 200이었다(아래 "재개").
- 5초마다 도구를 부르며 도는 요청에 `StopRuntimeSession`을 부르자 `statusCode` 200이 돌아왔고, 돌던 일은 그 뒤 10초에서 16초 사이에 멎었다. 멈춘 요청의 호출자는 멈춘 지 약 22초 뒤에 HTTP 500(`{"message":"An unexpected error occurred while processing the request."}`)을 받았다.

같은 명령을 두 번 돌리면 정책은 하나로 남고, 그때 찾은 세션마다 `StopRuntimeSession`을 다시 부른다.

## 멈춘 동안에도 심사의 시험 호출이 지나가는 이유

멈춤 정책의 `unless` 때문이다. 문장은 심사의 시험 호출 역할(`<prefix>-review-testcall-role`)인 호출을 forbid에서 뺀다. 그래서 팀이 고친 버전을 제출하면, 에이전트가 멈춘 동안에도 그 심사의 TestCall 단계가 에이전트를 게이트웨이로 부를 수 있다. 그렇게 되는 것은 아래의 관찰로 봤다.

2026-11-22의 확인 시험에서 이 정책이 걸린 동안 시험 호출 Lambda(`<prefix>-review-testcall`)를 직접 부르자 두 호출이 모두 기대대로였다(보통 질문은 200, 예시 access key가 든 질문은 403). 그 앞뒤의 사용자 호출은 403이었다. 같은 날의 운영 확인에서는 멈춘 동안 고친 버전의 심사 전체가 `SUCCEEDED`였다(아래).

## 세션을 어디서 찾나

`--session`을 주면 그 세션만 끝낸다. 주지 않으면 그 에이전트의 Runtime의 로그 그룹 `/aws/bedrock-agentcore/runtimes/<Runtime ID>-DEFAULT`에서 이름이 `runtime-logs-`로 시작하는 log stream을 찾고(`DescribeLogStreams`, `logStreamNamePrefix`), 그 뒤의 글자를 세션 ID로 쓴다. 최근 것만, 새 것부터 끝낸다.

2026-11-22의 확인 시험에서 본 것: 호출자가 에이전트 게이트웨이로 보낸 헤더 `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`의 세션 ID가 그 그룹의 log stream 이름 `runtime-logs-<세션 ID>`에 있었다. 요청이 도는 동안(30초에) 그 stream이 이미 있었다. 헤더 없이 부르면 세션 ID는 UUID(36자)였고 stream의 이름도 같은 모양이었다. 그것도 세션이므로 끝낸다. 그룹에는 `spans`라는 stream도 있었다. stream 목록은 어느 세션이 아직 도는지 말해 주지 않는다.

그래서 이렇게 한다.

- 최근이란: stream의 시간 셋, 곧 만든 때(`creationTime`), 마지막 이벤트(`lastEventTimestamp`), 마지막 수집(`lastIngestionTime`) 가운데 가장 늦은 것이 지난 30분 안이다. 만든 때는 stream이 생길 때 정해지므로, 1분 전에 생긴 stream의 세션도 찾는다. 세션을 연 뒤 stream이 얼마 만에 생기는지는 확인하지 않았다(2026-11-22에 요청을 연 지 30초에는 있었다). 서비스 모델의 `DescribeLogStreams` 설명(botocore 1.44.9)은 나머지 두 시간이 바로 맞지 않고 보통 한 시간 안에 갱신된다고 적는다(여기서는 확인하지 않았다).
- 그래서 30분보다 오래 돌고 있는 세션은 마지막 이벤트나 수집 시간이 지난 30분 안으로 갱신되어 있을 때만 찾는다. 갱신이 늦으면 찾지 못한다. 그런 세션은 `--session <ID>`로 준다.
- 30분 안에 stream이 있는 세션은 이미 끝났어도 끝내려 한다. 2026-11-22의 실행에서 `stop.sh`가 찾은 세션 여덟 가운데 여섯에 `StopRuntimeSession`은 `ResourceNotFoundException`(`Session <세션 ID> not found or has been terminated`)을 돌려줬다. 그 실행의 명령은 이 오류를 끝내지 못한 것으로 세어 1로 끝났다(진입은 막혔고 사고의 세션은 끝났다). 그래서 지금의 코드는 이 오류를 이미 끝난 세션으로 찍고(`already ended`) 실패로 세지 않는다. 다른 두 세션(사고의 세션과, 그 전에 연 세션 하나)에는 오류가 오지 않았다(`stopped`). 같은 허브에서 약 20분 뒤에 고친 코드로 다시 멈췄을 때는 세션 열둘을 찾아 열을 끝냈고, 남은 둘은 앞에서 끝낸 그 두 세션이었다. 둘 다 같은 `ResourceNotFoundException`이었고 `already ended`로 찍혔으며, 명령은 0으로 끝났다(`sessions stopped: 10, already ended: 2`). 끝낸 세션 ID로 다시 부르면 이 오류가 온다는 것이다. 첫 번째의 여섯 세션이 왜 이미 끝나 있었는지(쉬는 시간이 다 됐는지, 다른 까닭인지)와 세션이 언제까지 살아 있는지는 확인하지 않았다.
- 서비스 모델은 `runtimeSessionId`를 33~256자로 정한다. 그보다 짧은 이름의 stream은 건너뛴다. `--session`으로 준 ID가 그 길이가 아니면 보내지 않고 끝내지 못한 것으로 찍는다.
- 로그 그룹이 없으면 끝낼 세션 없이 넘어간다(오류로 멈추지 않는다). Runtime의 로그 그룹이 언제 생기는지는 확인하지 않았다.
- 서비스 모델의 설명대로 `DescribeLogStreams`는 이름의 앞부분(`logStreamNamePrefix`)과 이벤트 시간 순서(`orderBy` `LastEventTime`)를 함께 받지 않는다. 그래서 앞부분으로 모든 페이지를 읽고, 시간은 코드가 고른다.

Runtime의 ARN은 SSM `/<prefix>/agents/<에이전트>/runtime_arn`에서 읽는다. 이 값은 심사의 배포 역할이 쓸 수 있다. 그래서 그 에이전트의 Runtime(이 계정과 리전의 `runtime/<prefix>_<에이전트>-<10자>`)의 ARN이 아니면, 정책을 만들거나 세션을 끝내기 전에 거부한다. 에이전트 게이트웨이에 그 에이전트의 진입 target이 없을 때도 아무것도 하지 않고 거부한다.

## 재개

`resume.sh`는 `stop_agent_<에이전트>`를 지우고 사라질 때까지 기다린다. 그 밖의 것은 바꾸지 않는다. 멈춘 에이전트가 아니면 아무것도 바꾸지 않고 `was not stopped: nothing changed`를 찍는다. 2026-11-22의 확인 시험에서 같은 정책을 지우자, 지우기를 부른 때부터 12초와 16초 뒤의 사용자 호출이 200이었다. 같은 날의 운영 확인에서 `resume.sh`는 8초 걸렸고, 끝난 뒤 첫 호출부터(5초) 200이었다.

## 운영 확인에서 본 것

2026-11-22에 `us-west-2`, 접두어 `hub`의 허브에서 `make e2e-ops`(`e2e_checks/e2e_operations.py`)가 두 명령을 돌렸다. 사고 버전(`v2-loop`)의 `quality_agent`에게 사건 질문을 세션 ID 헤더와 함께 보내고, 도구 호출 알람의 알림이 온 뒤에 멈췄다.

- `stop.sh quality_agent`는 20초 걸렸다. 정책 `stop_agent_quality_agent`를 만들어 `ACTIVE`를 기다리고, 지난 30분의 stream에서 세션 여덟을 찾았다. 사고의 세션(헤더로 보낸 ID)도 그 안에 있었으므로 `--session`은 필요 없었다. 사고의 세션과 그 전에 연 세션 하나에는 오류가 오지 않았고, 나머지 여섯은 이미 끝난 세션이었다(위의 "세션을 어디서 찾나").
- 명령이 끝난 뒤 사용자의 호출은 403이었고 본문이 `stop_agent_quality_agent`를 담았다. 확인은 30초까지 다시 부르며 403을 기다렸고, 몇 번째 호출에서 403이 왔는지는 찍지 않았다. 되풀이가 찍는 `asking again` 줄은 명령이 끝나고 8초 뒤가 마지막이었고, 그 뒤 3분 동안 새 줄이 없었다(그때의 확인은 줄의 번호로 이것을 정했다. 지금의 확인은 줄마다 제 시간으로 정한다. [README의 "`make e2e-ops`가 확인하는 것"](../../README.md#make-e2e-ops가-확인하는-것)). 이웃(`release_review`, `docs_adk`는 에이전트 게이트웨이로, harness `spec_assistant`는 `InvokeHarness`로)은 그동안 답했다.
- 멈춘 채로 고친 버전(변형 없음)을 제출하자 심사가 `SUCCEEDED`였다(298초). 시험 호출의 보통 질문이 200이었으므로 멈춤 정책의 예외가 심사의 시험 호출을 지나게 했다. 승인된 뒤에도 사용자의 호출은 403이었다. 멈춤 정책은 `resume.sh`까지 남았다.
- `resume.sh quality_agent`는 8초 걸렸고 `stop_agent_quality_agent`를 지웠다. 그 뒤 첫 호출부터(5초) 200이었고 두 도구를 썼다.
- 같은 허브에서 다시 돌린 두 번째 실행(멈춤의 코드를 고친 뒤)에서도 같았다. `stop.sh`는 17초에 0으로 끝났고, 사고의 세션을 끝냈다. 되풀이의 마지막 줄은 명령이 끝나고 8초 뒤였고 그 뒤 3분 동안 새 줄이 없었다.

## 멈춤과 재개가 바꾸지 않는 것

- 멈춘 에이전트도 `entry_permit_<에이전트>`를 그대로 갖는다. 멈춤 정책은 그 옆에 거는 forbid다. 멈춤도 재개도 진입 permit, 도구 permit, guard, 전사 정책, Runtime을 건드리지 않는다.
- 그래서 반려와 심사가 보는 것은 바뀌지 않는다. 반려는 멈춤 정책을 보지 않는다. `entry_permit_<에이전트>`가 있는지로 정하고, 그 permit이 있으면 아무것도 지우지 않고 그 permit이 있다는 것만 말한다. 멈춘 에이전트에도 반려는 멈추기 전과 같은 일을 한다. 심사는 멈춤 정책을 만들지도 지우지도 않는다. 그래서 고친 버전이 승인되어도 멈춤 정책은 `resume.sh`를 돌릴 때까지 남는다.
- 반려와 `make destroy`가 에이전트의 것을 지울 때는 멈춤 정책도 지운다. 정책 가운데 가장 나중이다([호스팅 심사, 지우는 것과 순서](../hosting_review/README.md#지우는-것과-순서)).

## 한계

- 게이트웨이의 진입만 막는다. Runtime을 직접 부르는 길은 남는다. 이 허브를 만들기 전 2026-11-21의 확인 실행(따로 만든 echo 에이전트, 예외가 없는 forbid)에서, 게이트웨이 진입에 forbid가 걸린 동안 Runtime을 직접 부르자 200이었다. Runtime의 resource-based policy로 직접 호출을 막는 것은 해 보지 않았다.
- harness 에이전트는 에이전트 게이트웨이에 진입 target이 없어 이 명령으로 멈출 수 없다. `stop.sh`는 진입 target이 없는 에이전트를 거부한다.
- 30분보다 오래 돌고 있는 세션은 찾지 못할 수 있다(위의 "세션을 어디서 찾나").
- 멈춘 동안 `stop.sh`를 다시 돌리면 그때 찾은 세션마다 `StopRuntimeSession`을 부른다. 그사이에 심사의 시험 호출이 연 세션도 그 stream이 지난 30분 안의 것이면 그 안에 든다.
- AWS에서 해 보지 않은 것: 한 번도 없던 세션 ID에 `StopRuntimeSession`, 30분보다 오래 도는 세션. 에이전트가 모델의 답을 기다리던 때에 멈췄는지 도구를 부르던 때에 멈췄는지는 보지 않았다(운영 확인의 되풀이는 둘을 번갈아 한다).
- 명령이 부르는 API는 `ListGatewayTargets`, `GetParameter`(SSM), `ListPolicies`, `CreatePolicy`, `GetPolicy`, `DeletePolicy`, `DescribeLogStreams`, `StopRuntimeSession`이다. 이것에 필요한 IAM 권한은 확인하지 않았다. 확인 시험과 운영 확인은 관리자 권한의 자격 증명으로 돌았다.

## 파일

| 파일 | 역할 |
|---|---|
| `stop_agent.py` | 멈추기(`stop`), 재개(`resume`), 멈춰 있는지(`stopped`, 멈춤 정책이 있고 상태와 적용 모드가 모두 `ACTIVE`인지), SSM의 Runtime ARN 읽기와 확인(`runtime_arn`), 최근 세션 찾기(`recent_sessions`), 세션 헤더의 이름(`SESSION_HEADER`), 두 명령(`main`). |
| `stop.sh`, `resume.sh` | 위의 명령 둘. 리포의 `.env`를 `make`와 같은 규칙으로 읽고 `stop_agent`를 부른다. |
