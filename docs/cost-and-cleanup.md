# 요금과 지우기

[README](../README.md)로 돌아가기

허브가 떠 있는 동안 요금이 드는 것과, 허브를 지울 때 지워지는 것과 남는 것을 적습니다.

## 허브가 떠 있는 동안 요금이 드는 것

허브에는 켜 두는 서버가 없고, 대부분은 쓰는 만큼(호출 수, 실행 시간, 저장량) 요금이 붙습니다. 요금은 재지 않았고, 아래에 옮긴 요금 페이지와 안내서의 내용도 확인하지 않았습니다. 금액은 각 서비스의 요금 페이지를 봅니다.

| 자원 | 언제 요금이 드나 |
|---|---|
| Amazon Bedrock 모델(`MODEL_ID`) | 에이전트가 답할 때마다. 심사의 시험 호출과 `make e2e`의 호출도 들어갑니다. |
| AgentCore Runtime(승인된 에이전트마다 하나) | 에이전트가 호출을 처리하는 동안. harness 에이전트도 AgentCore가 만든 Runtime 하나 위에서 돌고, AgentCore 개발자 안내서(2026-11-22에 읽었습니다)는 harness에 따로 매기는 요금이 없다고 적습니다. |
| AgentCore Gateway 둘, Policy(policy engine과 가드레일 검사) | 호출과 권한 판단마다 |
| CodeBuild 프로젝트 둘 | 심사마다 build가 도는 분만큼. 2026-11-22의 심사들에서 Scan 단계는 31~180초, Deploy 단계는 244~269초였습니다. Deploy의 대부분은 Runtime이 `READY`가 되기를 기다리는 시간입니다. |
| Lambda 일곱(심사 다섯, 샘플 도구 하나, 커스텀 가드레일의 interceptor 하나), Step Functions, EventBridge, SNS, SQS | 실행과 메시지마다. interceptor는 에이전트 게이트웨이에 붙어 있는 동안 호출마다 두 번(요청과 답) 돕니다. |
| Amazon Bedrock Guardrails(커스텀 가드레일의 guardrail 하나) | interceptor가 붙어 있는 동안 호출마다 두 번 검사합니다. Amazon Bedrock 요금 페이지(2026-11-22에 읽었습니다)는 이 guardrail이 쓰는 두 필터를 무료로 적습니다. |
| S3(제출 버킷), CloudWatch Logs | 저장량과 들어온 로그만큼. Terraform이 만드는 로그 그룹 열둘은 14일 보관합니다. Runtime이 만드는 로그 그룹(`/aws/bedrock-agentcore/runtimes/...`)은 허브가 보관 기간을 정하지 않고, 에이전트를 지울 때 함께 지웁니다. |
| span(계정의 Transaction Search) | 계정의 설정이라 허브가 바꾸지 않습니다. 2026-11-22에는 span이 로그 그룹 `aws/spans`에 들어갔고, 반복하던 사고의 세션 하나(약 2분)가 span 729개를 남겼습니다. |
| CloudWatch 경보 둘(`<prefix>-tool-calls`, `<prefix>-guardrail-errors`) | 경보가 있는 동안 시간 단위로. CloudWatch 요금 페이지(2026-11-22에 읽었습니다)에는 무료 사용량이 있습니다. |
| CloudWatch의 읽기(`usage.sh`, `rollout.sh … report`, 사용량 보고의 Logs Insights 쿼리) | 부를 때마다. Logs Insights 쿼리는 `aws/spans`에서 그 시간 창을 읽습니다. |
| AWS Agent Registry, SSM 값(표준), IAM | 요금이 드는지 확인하지 않았습니다 |

## `make destroy`가 지우는 것과 남기는 것

`make destroy`는 지울 것의 계획을 보여 주고 `yes`를 받은 뒤 여섯 번에 나눠 지웁니다. `AUTO_APPROVE=1`로 묻지 않고만 돌렸으므로, `yes`를 묻는 대화는 확인하지 않았습니다.

1. 에이전트 게이트웨이에 붙은 커스텀 가드레일의 interceptor를 뗍니다. [커스텀 가드레일](../platform_team/custom_guardrail/README.md#붙이고-떼는-명령)
2. 전사 정책의 모드(SSM `/<prefix>/policies/` 아래의 값)를 지웁니다. 값이 남은 채로 지우는 것은 해 보지 않았습니다. [전사 정책](../platform_team/company_policy/README.md#make-destroy)
3. 심사와 `make preload`가 에이전트마다 만든 것을 지웁니다. 정책, 에이전트 게이트웨이의 target, Runtime `<prefix>_<에이전트>`, harness, 둘의 로그 그룹, 제출 버킷의 코드 패키지(`packages/<에이전트>/`), 실행 역할, SSM 값, 카탈로그 레코드입니다. [호스팅 심사, 지우는 것과 순서](../platform_team/hosting_review/README.md#지우는-것과-순서)
4. `make seed`가 넣은 공유 도구 레코드를 지웁니다.
5. 카탈로그에 남은 레코드를 종류와 이름에 상관없이 모두 지우고 하나씩 출력합니다.
6. `terraform destroy`로 나머지를 지웁니다. 게이트웨이 둘, policy engine, 카탈로그, Lambda, guardrail, CodeBuild 프로젝트, state machine, 역할과 권한 경계, 제출 버킷(모든 version까지), 알림 주제와 큐, 경보, 로그와 trace 전달, SSM 값, 로그 그룹입니다.

마지막에 `e2e_checks/check_cleanup.py`가 접두어로 시작하는 자원이 남았는지 찾아보고 `still present: nothing` 또는 남은 종류를 출력합니다. 읽기만 합니다. 2026-11-22에는 에이전트 넷(그 가운데 harness 하나)이 있는 허브를 지운 뒤에도 `still present: nothing`이었고, 계정의 다른 Runtime, `CDKToolkit` 스택, 로그 그룹 `aws/spans`, Transaction Search의 설정은 그대로 있었습니다.

허브가 지우지 않는 것은 이렇습니다.

- 로그 그룹 `aws/spans`는 계정의 것이라 지우지 않고, 그곳의 span은 계정의 보관 기간(2026-11-22에 30일)까지 남습니다. Transaction Search가 꺼진 계정에서는 해 보지 않았습니다. [모니터링](../platform_team/agent_monitoring/README.md#무엇이-어디에-남는가)
- 허브는 CDK를 쓰지 않아 계정의 CDK bootstrap(스택 `CDKToolkit`과 그 bucket)에 손대지 않습니다. 심사가 CLI로 배포하던 이전의 코드가 그 bucket에 남긴 에이전트 코드의 사본(에이전트마다 31 MB 남짓의 zip)과 CDK template도 지우지 않습니다.
- Runtime과 harness의 workload identity, harness가 도는 Runtime(`harness_<prefix>_<에이전트>`)은 허브가 따로 지우지 않습니다. 2026-11-22에는 그 주인과 함께 사라졌습니다.
