# 알려진 한계

[README](../README.md)로 돌아가기

이 샘플의 한계를 적습니다. 자세한 것은 각 기능의 문서에 있습니다. Omni 조회와 AWS 콘솔의 화면은 들어 있지 않습니다.

## 진입의 통제

- 진입 정책, 비밀값 검사, 전사 정책, 커스텀 가드레일, 멈춤 명령은 모두 에이전트 게이트웨이에 걸립니다. Runtime을 직접 부르는 길(`InvokeAgentRuntime`)과 harness 에이전트(`InvokeHarness`)에는 닿지 않습니다.
- 멈춘 에이전트도 Runtime을 직접 부르면 답합니다. 2026-11-21에 진입에 forbid가 걸린 동안 Runtime을 직접 부르자 200이었습니다.
- 에이전트 멈추기는 30분보다 오래 돌고 있는 세션을 찾지 못할 수 있습니다. [에이전트 멈추기와 재개, 한계](../platform_team/agent_stop/README.md#한계)
- harness 에이전트(`spec_assistant`)는 진입 target이 없어 진입의 통제를 받지 않고, 멈춤 명령으로 멈출 수도 없습니다. 도구 호출만 도구 게이트웨이의 정책을 지납니다.
- 서비스 모델의 `InvokeHarness`는 호출마다 도구, 쓸 수 있는 도구의 목록, 모델, 지시문을 받으므로, 그것을 부를 수 있는 사람은 이 값들을 바꿔 보낼 수 있습니다. 바꿔 보내는 것은 해 보지 않았습니다. 허브의 역할 가운데 `InvokeHarness`를 가진 것은 없습니다.
- harness가 permit이 없는 도구를 부를 때 도구 게이트웨이가 거부하는지는 확인하지 않았습니다. 그 도구를 `allowedTools`에 더해 두 번 물었지만 모델이 부르지 않았습니다. [spec_assistant, 허브에서 받는 통제](../dev_team/preloaded_agents/spec_assistant/README.md#허브에서-받는-통제)
- 커스텀 가드레일의 interceptor Lambda가 실패하는 동안 에이전트 게이트웨이는 모든 요청을 거부하고, 경보가 알립니다. 답은 한 번에 오는 JSON만 확인했고, 스트리밍 응답은 확인하지 않았습니다. [커스텀 가드레일](../platform_team/custom_guardrail/README.md#확인한-것과-하지-않은-것)

## 호스팅 심사

- 시험 호출은 HTTP 상태만 보고 답의 내용은 보지 않습니다. [호스팅 심사, 시험 호출](../platform_team/hosting_review/README.md#알려진-한계-시험-호출)
- 간접 의존성은 검사한 것과 배포한 것이 같다고 보장되지 않습니다. `requirements.txt`에 적은 줄은 검사와 배포가 같은 파일을 씁니다. [호스팅 심사, requirements.txt 규칙](../platform_team/hosting_review/README.md#requirementstxt-규칙)
- 심사가 도는 동안에는 반려가 거부됩니다. [호스팅 심사, 반려의 한계](../platform_team/hosting_review/README.md#한계)
- 배포(Deploy)의 역할 하나가 모든 심사에 쓰입니다. 배포 build 안에서 코드를 실행할 수 있으면 다른 에이전트의 Runtime을 바꾸거나, 그 실행 역할을 넘기거나, 그 코드 패키지(제출 버킷의 `packages/`)를 덮어쓰거나, 그 `runtime_arn`을 쓸 수 있습니다.
- 배포 역할의 정책은 이름이 `<prefix>_`로 시작하지 않는 Runtime의 만들기를 막지 않습니다. 그런 Runtime은 허브의 정리가 지우지 않고, 실제로 만들어지는지는 해 보지 않았습니다. [호스팅 심사, 알려진 한계](../platform_team/hosting_review/README.md#알려진-한계-배포-단계의-권한)

## 승인된 에이전트의 새 버전

- 새 버전은 Deploy가 끝나면 시험 호출과 승인을 기다리지 않고 사용자의 호출을 받습니다. 이전 버전의 `entry_permit_<에이전트>`가 남아 있기 때문입니다.
- 심사는 시험 호출 하나로 새 버전을 봅니다. 사고 버전(`v2-loop`)도 시험 호출에는 반복하지 않아 심사를 지났습니다.
- 새 버전이 심사에서 떨어져도 되돌리지 않습니다. Grant가 바꾼 도구 정책은 그대로이고, Deploy가 끝났으면 떨어진 버전의 코드가 돕니다. [심사가 실패했을 때](../platform_team/hosting_review/README.md#심사가-실패했을-때)
- 새 버전을 반려하면 레코드만 `REJECTED`가 됩니다. 사용자를 막으려면 `stop.sh <에이전트>`를 돌리고 고친 버전을 다시 제출합니다.
- 같은 레코드의 심사 둘이 겹치면 뒤의 것이 Read에서 멈춥니다.
- 승인 전의 사용자 호출, 도구가 바뀌는 새 버전, 떨어지는 새 버전, 겹치는 심사는 코드가 그렇게 하고 AWS에서는 해 보지 않았습니다. [호스팅 심사, 승인된 에이전트의 새 버전](../platform_team/hosting_review/README.md#승인된-에이전트의-새-버전)

## 개발팀의 권한과 기록

- 개발팀 역할의 카탈로그 권한은 모든 레코드에 걸립니다. [개발팀의 권한](../platform_team/dev_access/README.md#카탈로그-권한의-범위)
- 개발팀 역할 하나가 모든 팀에 쓰이므로, 개발자는 모든 에이전트의 Runtime 로그 줄을 읽을 수 있습니다. harness 에이전트의 것은 읽지 못합니다. [개발팀의 권한](../platform_team/dev_access/README.md#mcp-endpoint와-로그-권한)
- 에이전트의 실행 역할은 X-Ray에 trace를 `"*"`로 쓸 수 있고, namespace `bedrock-agentcore`의 메트릭이면 어느 것이든 쓸 수 있습니다. 그 namespace는 계정의 다른 에이전트도 씁니다. [호스팅 심사, 에이전트 실행 역할의 상한](../platform_team/hosting_review/README.md#에이전트-실행-역할의-상한권한-경계)
- 2026-11-22에 span은 계정의 로그 그룹 `aws/spans`에 들어갔고, 모델의 토큰 수와 호출에 쓴 access key ID를 담았습니다. [모니터링, 에이전트의 trace](../platform_team/agent_monitoring/README.md#에이전트의-trace)

## 예시 에이전트

- `release_review`의 판정은 모델 호출 한 번입니다. [release_review, 한계](../dev_team/release_review/README.md#한계)
