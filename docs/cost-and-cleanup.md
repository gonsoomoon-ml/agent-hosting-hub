# 요금과 지우기

[README](../README.md)로 돌아가기

허브가 떠 있는 동안 요금이 드는 것과, 허브를 지울 때 지워지는 것과 남는 것을 적는다.

## 허브가 떠 있는 동안 요금이 드는 것

허브가 올리는 자원과, 각 서비스의 요금 방식으로 보아 요금이 드는 때다. 이 실행은 요금을 재지 않았으니 금액은 각 서비스의 요금 페이지를 본다. 허브는 켜 두는 서버가 없고, 대부분은 쓰는 만큼(호출 수, 실행 시간, 저장량) 요금이 붙는다.

| 자원 | 언제 요금이 드나 |
|---|---|
| Amazon Bedrock 모델(`MODEL_ID`) | 에이전트가 답할 때마다. 심사의 시험 호출과 `make e2e`의 호출도 포함된다. |
| AgentCore Runtime(승인된 에이전트마다 하나. harness 에이전트는 AgentCore가 만든 Runtime 하나 위에서 돈다) | 에이전트가 호출을 처리하는 동안. AgentCore 개발자 안내서("AgentCore harness", 2026-11-22에 읽었다)는 harness에 따로 매기는 요금이 없고 쓰는 AgentCore 기능만큼 낸다고 적는다. 여기서는 확인하지 않았다. |
| AgentCore Gateway 둘, Policy(policy engine과 가드레일 검사) | 호출과 권한 판단마다 |
| CodeBuild 프로젝트 둘 | 심사마다 build가 도는 분만큼. 이 실행에서 Scan 단계는 28~47초, Deploy 단계는 310~363초였다. 고친 뒤의 실행에서는 Scan 27~71초, Deploy 315~316초였다. Deploy의 값은 CLI로 배포하던 때의 것이다([시작하기](getting-started.md#일곱-명령)의 "일곱 명령"). 지금의 배포 단계에서는 Deploy 단계가 244~266초였고, 그 가운데 221~241초는 build가 Runtime이 `READY`가 되기를 기다린 시간이다. 심사를 다진 뒤의 실행에서는 Scan 31~36초, Deploy 257초와 264초(그 가운데 `READY`를 기다린 시간 231초와 242초)였다. |
| Lambda 일곱(심사 다섯, 샘플 도구 하나, 커스텀 가드레일의 interceptor 하나), Step Functions, EventBridge, SNS, SQS | 실행과 메시지마다. interceptor는 에이전트 게이트웨이에 붙어 있는 동안 호출마다 두 번(요청과 답) 돈다. 운영을 확인한 실행에서 그 Lambda의 로그에 요청 지점과 답 지점의 줄이 함께 있었다([확인한 것](checks.md#make-e2e-ops가-확인하는-것)의 "`make e2e-ops`가 확인하는 것"). |
| Amazon Bedrock Guardrails(커스텀 가드레일의 guardrail 하나) | interceptor가 붙어 있는 동안 호출마다 두 번(요청과 답) 검사한다. Amazon Bedrock 요금 페이지(2026-11-22에 읽었다)는 검사한 글의 양(text unit, 1,000자까지가 하나)을 필터마다 매기고, 이 guardrail이 쓰는 두 필터(낱말 필터, 정규식의 민감 정보 필터)는 무료라고 적는다. 여기서는 요금을 확인하지 않았다. |
| S3(제출 버킷: 제출물과 에이전트의 코드 패키지), CloudWatch Logs | 저장량과 들어온 로그만큼. Terraform이 만드는 로그 그룹 열둘(Lambda 일곱, CodeBuild 둘, state machine 하나, 게이트웨이 둘)은 14일 보관한다. 에이전트와 게이트웨이의 span은 계정의 Transaction Search가 받는다(2026-11-22의 실행에서는 로그 그룹 `aws/spans`에 들어갔다). 그 설정은 계정의 것이라 허브가 바꾸지 않는다. span의 요금은 확인하지 않았다. 양의 예로, 운영을 확인한 실행의 35분 동안 도구 게이트웨이의 로그 그룹에 줄 494개가 들어왔고, 반복하던 사고의 세션 하나(약 2분)가 `aws/spans`에 span 729개를 남겼다. Runtime이 만드는 로그 그룹(`/aws/bedrock-agentcore/runtimes/...`)에는 허브가 보관 기간을 정하지 않는다. 에이전트를 지울 때 함께 지운다. |
| CloudWatch 경보 둘(모니터링의 `<prefix>-tool-calls`, 커스텀 가드레일의 `<prefix>-guardrail-errors`) | 경보가 있는 동안. CloudWatch 요금 페이지(2026-11-22에 읽었다)는 경보를 그 메트릭마다 시간 단위로 매기고, 무료 사용량(표준 해상도의 경보 메트릭 10개)이 있다고 적는다. 여기서는 확인하지 않았다. |
| CloudWatch의 읽기(`usage.sh`와 `rollout.sh … report`의 메트릭 읽기, 사용량 보고의 `session_summary`가 `aws/spans`에 거는 Logs Insights 쿼리) | 부를 때마다. Logs Insights 쿼리는 계정의 `aws/spans` 가운데 그 시간 창을 읽는다. 요금은 확인하지 않았다. |
| AWS Agent Registry, SSM 값(표준), IAM | 요금이 드는지 확인하지 않았다 |

## `make destroy`가 지우는 것과 남기는 것

`make destroy`는 지울 것의 계획을 보여 주고 `yes`를 받은 뒤(이 실행은 `AUTO_APPROVE=1`로 묻지 않고 돌렸다) 여섯 번에 나눠 지운다.

1. 에이전트 게이트웨이에 붙은 커스텀 가드레일의 interceptor(Terraform 밖. `guardrail.sh attach`가 붙인다). 가장 먼저 떼므로, 게이트웨이가 지워진 Lambda를 가리키는 일이 없다. 허브가 올라와 있지 않거나 게이트웨이가 없으면 아무것도 하지 않는다. [커스텀 가드레일](../platform_team/custom_guardrail/README.md#붙이고-떼는-명령)
2. 전사 정책의 모드(SSM `/<prefix>/policies/` 아래의 값. `rollout.sh`가 적는다). 에이전트보다 먼저 지우므로, 그 뒤에 모드를 읽는 승인은 전사 정책을 걸지 않는다(지우기 직전에 모드를 읽은 승인은 그 뒤에도 걸 수 있다. 코드로 보면 그렇다). 정책 자체는 다음 단계가 에이전트와 함께 지운다. 2026-11-22의 `make destroy`들은 이 단계를 돌렸지만 지울 값이 없을 때뿐이었다(`0 removed`. 운영을 확인한 실행에서도 그 앞에서 `rollout.sh guard_prompt off`가 값을 지웠다). 값이 남은 채로 지우는 것은 해 보지 않았다. [전사 정책](../platform_team/company_policy/README.md#make-destroy)
3. 심사가 에이전트마다 만든 것(Terraform 밖): 정책 넷 이상(`entry_permit_`, `review_permit_`, `tool_`, `guard_secret_`, 운영 중에 더하면 `guard_prompt_`, `stop_agent_`), 에이전트 게이트웨이의 target, Runtime `<prefix>_<에이전트>`, Runtime의 로그 그룹, `make preload`가 만든 harness `<prefix>_<에이전트>`와 그 harness가 도는 Runtime(`harness_<prefix>_<에이전트>`)의 로그 그룹, 제출 버킷의 코드 패키지(`packages/<에이전트>/`), 실행 역할, SSM 값, 그리고 에이전트의 카탈로그 레코드. 순서와 이유는 [호스팅 심사, 반려](../platform_team/hosting_review/README.md#지우는-것과-순서)에 있다. Runtime의 workload identity는 허브가 따로 지우지 않는다. CLI로 배포하던 때의 실행에서는 Runtime과 함께 사라졌다. API로 만든 Runtime에서도 2026-11-22의 실행에서 Runtime과 함께 사라졌다(`reject.sh` 한 번과 `make destroy`의 Runtime 둘, 목록으로 확인했다). 그 이름은 Runtime ID와 같다. harness가 도는 Runtime(`harness_<prefix>_<에이전트>`)과 그 workload identity는 허브가 따로 지우지 않는다. 2026-11-22의 `make destroy`에서는 harness를 지우자 둘 다 함께 사라졌다(목록으로 확인했다). 그 Runtime의 로그 그룹은 정리가 지운다.
4. `make seed`가 넣은 공유 도구 레코드.
5. 그래도 카탈로그에 남은 레코드(AGENT가 아니거나 이름 규칙에 맞지 않아 3에서 찾지 못한 것). 종류와 이름에 상관없이 모두 지우고 하나씩 출력한다. 카탈로그는 허브의 것이고 다음 단계에서 지워진다.
6. `terraform destroy`: 게이트웨이 둘, policy engine과 그 정책, 카탈로그, Lambda, 커스텀 가드레일의 guardrail과 그 버전, CodeBuild 프로젝트, state machine, rule, 역할과 권한 경계, 제출 버킷(모든 version까지), 알림 주제와 큐, 경보, 게이트웨이 둘의 로그와 trace 전달(source, destination, delivery), SSM 값, 로그 그룹.

마지막에 `e2e_checks/check_cleanup.py`가 접두어로 시작하는 자원이 남았는지 종류마다 찾아보고 `still present: nothing`(또는 남은 종류)을 출력한다. 읽기만 한다.

span은 계정의 CloudWatch Transaction Search가 받는다. 2026-11-22의 실행(계정의 Transaction Search가 켜져 있었다)에서는 에이전트와 에이전트 게이트웨이의 span이 계정의 로그 그룹 `aws/spans`에 들어갔다. 그 로그 그룹은 계정의 것이라 `make destroy`가 지우지 않으므로, 그곳에 들어간 span은 계정의 보관 기간(그날 30일)까지 남는다. Runtime의 로그 그룹(안내서가 span이 갈 수 있다고 적는 다른 곳)은 `make destroy`가 에이전트와 함께 지운다. Transaction Search가 꺼진 계정에서는 해 보지 않았다. [모니터링](../platform_team/agent_monitoring/README.md#무엇이-어디에-남는가)

허브는 CDK를 쓰지 않으므로 계정의 CDK bootstrap(스택 `CDKToolkit`과 그 bucket)에 손대지 않는다. CLI로 배포하던 때의 실행은 그 bucket에 에이전트 코드의 사본(에이전트마다 31 MB 남짓의 zip 하나)과 CDK template을 남겼다. 허브는 이 사본을 지우지 않는다.

CLI로 배포하던 때의 실행에서는 그 밖에 남은 것이 없었다. `check_cleanup.py`가 `still present: nothing`을 출력했고, 게이트웨이, 카탈로그, Runtime마다 서비스가 만든 workload identity도 그 주인과 함께 사라졌다(목록으로 확인했다). 지금의 배포로 만든 허브를 2026-11-22에 `make destroy`로 지웠을 때도(승인된 에이전트 둘, 그 가운데 하나는 Runtime 버전 3) `check_cleanup.py`가 `still present: nothing`을 출력했다. 이름이 `AgentCore-`로 시작하는 스택, `hub_`로 시작하는 Runtime과 workload identity, 제출 버킷(그래서 `packages/` 아래의 패키지)도 남지 않았고, 계정의 `CDKToolkit` 스택은 그대로 있었다(목록으로 확인했다). 심사를 다진 뒤의 실행(제출 버킷에 bucket 정책이 있다)에서도 `make destroy`가 `still present: nothing`을 출력했고, `hub_`로 시작하는 Runtime과 workload identity가 남지 않았고, `CDKToolkit` 스택은 그대로 있었다(목록으로 확인했다). 에이전트 둘을 미리 올려 둔 허브를 지운 실행에서도 `still present: nothing`이었고(`check_cleanup.py`는 harness와 `harness_<prefix>_` 모양의 이름도 찾는다), harness, `hub_`나 `harness_`로 시작하는 Runtime과 workload identity가 남지 않았고, 계정의 Runtime과 `CDKToolkit` 스택은 그대로 있었다(목록으로 확인했다). 운영을 확인한 실행의 허브(에이전트 넷, 그 가운데 harness 하나)를 지운 뒤에도 `still present: nothing`이었다. 접두어로 시작하는 Amazon Bedrock Guardrails의 guardrail, CloudWatch 경보, harness, 로그 전달(source, destination, delivery), 로그 그룹, SSM 값, SQS 큐, `hub`나 `harness`가 든 Runtime과 workload identity가 남지 않았고, 계정의 Runtime과 `CDKToolkit` 스택, 로그 그룹 `aws/spans`와 Transaction Search의 설정은 그대로 있었다(목록으로 확인했다).
