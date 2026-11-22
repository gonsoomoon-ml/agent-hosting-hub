# 호스팅 심사

개발팀이 올린 에이전트를 허브에 올려도 되는지 자동으로 심사하고, 통과하면 올리고 승인한다. 카탈로그의 record가 승인 요청 상태(`PENDING_APPROVAL`)가 되면 EventBridge rule `<prefix>-on-submit`이 Step Functions의 state machine `<prefix>-review`를 시작한다. state machine은 순서와 기다림과 실패했을 때의 갈림만 맡고, 일은 단계마다 Lambda 함수나 CodeBuild 프로젝트가 한다. 어느 단계든 실패하면 알림 주제(`<prefix>-alerts`)에 알리고 심사를 멈춘다. record는 `PENDING_APPROVAL`에 남는다.

일을 나누는 기준은 하나다. 제출된 코드를 다루는 단계(Scan, Deploy)는 CodeBuild가 하고, 권한을 줄 수 없다. 권한을 주는 단계(Read, Grant, Entry, TestCall, Approve)는 Lambda가 하고, 제출된 코드를 열지 않는다. 단계마다 역할이 따로 있다.

## 개념도에서의 위치

"호스팅 심사" 상자다. ③ "심사 시작"에서 시작해 ④ "에이전트에 도구 권한 부여"(Grant), ⑤ "에이전트 배포"(Deploy), ⑥ "요청 허용, 승인 표시"(Approve)를 한다. 앞의 Read와 Scan은 상자 안의 "자동 점검"이고, Entry와 TestCall은 그림에 그리지 않았다. 실패하면 ④-1 "심사 실패 알림"(점선)으로 빠진다.

## 일곱 단계

| # | 단계 | 누가 돌리나(역할) | 할 수 있는 일 | 할 수 없는 일 |
|---|---|---|---|---|
| 1 | Read | Lambda `<prefix>-review-read` (`<prefix>-review-read-role`) | 카탈로그의 record를 읽고(`GetRegistryRecord`) 신청서를 확인한다. 코드가 있는 곳(S3 key와 object version)을 다음 단계에 넘긴다. | 제출된 코드 읽기, record 바꾸기, 정책 만들기 |
| 2 | Scan | CodeBuild `<prefix>-review-scan` (`<prefix>-review-scan-role`) | 신청서에 적힌 version의 제출물과 허브의 코드 묶음을 읽는다. 압축을 풀어 모양을 확인하고 `requirements.txt`를 `pip-audit`로 검사한다. 자기 build 로그를 쓴다. | 이것 말고는 모두. 역할, 정책, target, record, SSM에 손댈 수 없다. |
| 3 | Grant | Lambda `<prefix>-review-grant` (`<prefix>-review-grant-role`) | 에이전트의 실행 역할(`<prefix>-agent-<에이전트>-role`)을 권한 경계 `<prefix>-agent-boundary`를 달아서 만들고, 신청서에 적힌 도구마다 도구 게이트웨이에 `tool_permit`을 건다. | 경계 없이 역할 만들기, 경계를 바꾸거나 떼기, 에이전트 게이트웨이에 정책 걸기, 다른 이름의 역할 만들기, 제출된 코드 읽기 |
| 4 | Deploy | CodeBuild `<prefix>-review-deploy` (`<prefix>-review-deploy-role`) | 제출물과 허브의 코드 묶음을 읽고, `agentcore deploy`로 Runtime을 올린다(CDK bootstrap 역할을 맡아서). Runtime ARN을 SSM `/<prefix>/agents/<에이전트>/runtime_arn`에 쓴다. | 정책, target, record, IAM 역할을 직접 만들거나 바꾸기(`bedrock-agentcore`의 action도 `iam:PassRole`도 없다). 아래의 한계를 보라. |
| 5 | Entry | Lambda `<prefix>-review-entry` (`<prefix>-review-entry-role`) | SSM에서 Runtime ARN을 읽고, 에이전트 게이트웨이에 그 에이전트의 target을 만든다. 시험 호출만 들어오게 하는 `entry_permit_review`와 비밀값을 막는 `guard_secret`을 건다. | 도구 게이트웨이에 정책 걸기, record 승인, 제출된 코드 읽기 |
| 6 | TestCall | Lambda `<prefix>-review-testcall` (`<prefix>-review-testcall-role`) | 에이전트 게이트웨이로 에이전트를 두 번 부른다. 보통 질문에는 답이 와야 하고, 예시 access key가 든 질문은 거부(403)돼야 한다. 승인 전에 들어올 수 있는 것은 이 역할뿐이다. | 에이전트 게이트웨이를 부르는 것 말고는 모두 |
| 7 | Approve | Lambda `<prefix>-review-approve` (`<prefix>-review-approve-role`) | record를 다시 읽어 심사를 시작할 때의 신청서와 같은지 확인한다. 같으면 사용자가 들어오게 하는 `entry_permit`을 걸고, record를 `APPROVED`로 바꾼다. 그사이에 바뀌었으면 승인하지 않고 알림으로 빠진다. | 바뀐 record 승인하기, 도구 게이트웨이에 정책 걸기, 역할 만들기, 제출된 코드 읽기 |

Lambda 단계는 모두 자기 로그만 쓸 수 있다. 정책을 만드는 단계(Grant, Entry, Approve)는 policy engine에서 정책을 만들고 읽고 지울 수 있고, 그 정책이 가리키는 게이트웨이 하나에만 그 게이트웨이를 확인하는 권한(`ManageResourceScopedPolicy`, `GetGateway`, `ListGatewayTargets`, `GetGatewayTarget`, `InvokeGateway`)을 갖는다. 정책이 게이트웨이를 가리키면 정책을 만드는 쪽에 이 권한이 있어야 한다는 것은 실행해서 찾았다.

Lambda 단계는 제한 시간(가장 길어도 900초)에 끊기기 전에 스스로 멈춘다. 처리기가 제한 시간 60초 전을 마감으로 정하고, 단계의 기다림(정책 하나에 300초, target에 300초, 시험 호출의 재시도)은 저마다의 한도와 마감까지 남은 시간 가운데 짧은 쪽만 기다린다. 마감까지 정책이 `ACTIVE`가 되지 않으면 그 정책을 지우고, 알림에는 Lambda의 시간 초과가 아니라 단계가 낸 오류가 간다.

지휘하는 역할도 둘 있다. state machine의 역할 `<prefix>-sfn-role`은 다섯 Lambda를 부르고, 두 CodeBuild 프로젝트를 시작하고 기다리고, 알림 주제에 보내고, 실행 로그를 쓴다. rule의 역할 `<prefix>-events-role`은 이 state machine을 시작하는 것만 한다.

## 제출함

S3 bucket `<prefix>-<account>-<region>`이다. 버전 관리를 켜 두었다. 개발팀 역할(`dev_access`)은 `submissions/` 아래에 올릴 수 있다(`s3:PutObject`). 신청서에는 올린 object의 version을 적고, Scan과 Deploy는 꼭 그 version을 읽는다. 그래서 검사한 코드와 올리는 코드가 같다. 허브의 코드 묶음(`build/platform_team.zip`)은 Terraform이 `platform/platform_team.zip`에 올려 두고, 두 build가 내려받아 `submission_check.py`와 `deploy_build.py`를 돌린다.

## 에이전트 실행 역할의 상한(권한 경계)

Grant의 역할은 IAM 역할을 만들고 그 inline 정책을 쓸 수 있다. IAM은 inline 정책의 내용을 조건으로 막지 못하므로, 경계가 없다면 이 단계는 무엇이든 할 수 있는 역할을 만들 수 있다. 그래서 Grant는 권한 경계 `<prefix>-agent-boundary`가 달린 역할에만 `CreateRole`과 `PutRolePolicy`를 할 수 있다(`iam:PermissionsBoundary` 조건). 경계를 바꾸거나 떼는 권한은 없다. 경계는 에이전트 실행 역할에 필요한 것의 상한이다. 그 내용은 Runtime 로그, 도구 게이트웨이 호출, 모델 호출(inference profile과 foundation model), workload identity의 토큰이다. 역할의 실제 권한은 inline 정책과 경계가 함께 허용하는 것뿐이다. 그래서 inline 정책에 무엇이 들어가도 역할은 이 상한을 넘지 못한다. 경계가 실행 역할의 action을 모두 허용하는지는 단위 시험이 확인한다(`tests/test_review_iam.py`).

## 알려진 한계: 배포 단계의 권한

배포 단계는 AgentCore CLI(`agentcore deploy`)로 올린다. CLI는 CDK를 쓰고, CDK는 계정의 bootstrap 역할(`cdk-hnb659fds-*`)을 맡아 CloudFormation 스택을 만든다. 배포 역할 자체는 이 bootstrap 역할을 맡는 권한만 갖는다. 다만 CloudFormation은 CDK의 실행 역할(`cdk-hnb659fds-cfn-exec-role-*`)로 자원을 만들고, 기본 bootstrap에서 이 실행 역할의 권한은 넓다(`AdministratorAccess`). 그래서 배포 단계에서는 역할을 나눈 효과가 약하다. 검사 단계의 분리는 그대로다.

운영 환경이라면 CDK를 전용 qualifier로 다시 bootstrap하고, 실행 역할에는 Runtime 스택에 필요한 권한만 담은 실행 정책(`--cloudformation-execution-policies`)을 준다. 배포 역할은 그 qualifier의 역할만 맡게 한다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/main.tf` | 제출함과 코드 묶음, Lambda 다섯, CodeBuild 둘, state machine, 시작하는 rule, 로그 그룹(모두 Terraform이 만들고 `terraform destroy`가 지운다). 새 rule은 첫 이벤트를 놓치므로 90초를 기다린다(`time_sleep.rule_settles`). |
| `terraform/iam.tf` | 단계마다의 역할과 정책 문서(`read`, `scan`, `grant`, `deploy`, `entry`, `testcall`, `approve`), 에이전트 실행 역할의 권한 경계(`agent_boundary`), state machine과 rule의 역할, 개발팀 역할에 붙이는 업로드 권한. |
| `terraform/review_machine.asl.json.tftpl` | state machine의 정의. 모든 단계의 실패는 `Notify`(SNS)로 가서 `Failed`로 끝난다. |
| `terraform/variables.tf`, `terraform/outputs.tf` | 다른 모듈에서 받는 값(게이트웨이, policy engine, 카탈로그, 알림 주제, 개발팀 역할)과 내보내는 값(`bucket`, `machine_arn`. 시작점이 SSM `/<prefix>/platform/`에 적는다). |
| `review_steps.py` | Lambda 단계 다섯(Read, Grant, Entry, TestCall, Approve)의 코드. |
| `lambda_handler.py` | Lambda의 진입점. 환경 변수 `ACTION`이 단계를 고르고, 제한 시간 60초 전을 단계의 마감으로 넘긴다. |
| `buildspec_scan.yml`, `submission_check.py` | 검사 단계. 제출물의 압축을 안전하게 풀고 모양과 `requirements.txt`를 확인한 뒤 `pip-audit`를 돌린다. |
| `buildspec_deploy.yml`, `deploy_build.py`, `runtime_skeleton/` | 배포 단계. 플랫폼의 배포 설정에 제출된 코드를 넣어 `agentcore deploy`를 돌린다(`runtime_skeleton/README.md`). |
