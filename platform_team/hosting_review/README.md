# 호스팅 심사

개발팀이 올린 에이전트를 허브에 올려도 되는지 자동으로 심사하고, 통과하면 올리고 승인한다. 카탈로그의 record가 승인 요청 상태(`PENDING_APPROVAL`)가 되면 EventBridge rule `<prefix>-on-submit`이 Step Functions의 state machine `<prefix>-review`를 시작한다. state machine은 순서와 기다림과 실패했을 때의 갈림만 맡고, 일은 단계마다 Lambda 함수나 CodeBuild 프로젝트가 한다.

심사할 것이 아닌 record는 Read가 건너뛴다. AGENT가 아닌 record(공유 도구)와, 신청서의 `framework`가 `harness`인 record(코드가 없다)다. Read는 이것을 신청서의 다른 확인보다 먼저 보므로, 건너뛰는 record에는 코드의 위치가 없어도 된다. Read는 `{"skip": "<이유>"}`를 돌려주고, state machine은 Read 뒤의 Choice `Reviewable`에서 Succeed `Skipped`로 가서 끝난다. 알림은 가지 않고, 아무것도 만들지 않는다. 2026-11-22의 실행에서 `make seed`가 공유 도구 record `parts-tools`(MCP)를 승인 요청 상태로 바꾸자 심사가 시작했고, Read, `Reviewable`, `Skipped`를 지나 1.7초 만에 `SUCCEEDED`로 끝났다. SNS에 보내는 단계는 없었다(실행 기록으로 확인했다). `framework`가 `harness`인 record도 2026-11-22의 실행에서 봤다. `make preload`가 harness 에이전트 `spec_assistant`의 record를 승인 요청 상태로 바꾸자 심사가 시작했고, Read, `Reviewable`, `Skipped`를 지나 0.7초 만에 `SUCCEEDED`로 끝났다(실행 기록으로 확인했다).

어느 단계든 실패하면 알림 주제(`<prefix>-alerts`)에 알리고 심사를 멈춘다. 알림을 보내는 단계(`Notify`)가 실패하면 5초, 10초, 20초 뒤에 다시 해 본다(`Retry`, 세 번까지. 실패한 적이 없어서 AWS에서는 해 보지 않았다). 알림의 제목은 `Hosting review failed at <단계>`이고, 내용은 심사의 상태(에이전트의 신청서 `spec`, 실패한 단계 `failedStep`, 오류 `error`)를 담은 JSON이다. Scan이나 Deploy가 실패하면 `error`에 build의 기록이 들어 있고, 거기 적힌 로그 그룹과 stream에서 build 로그를 찾는다. Read가 실패하면 신청서를 읽기 전이므로 `spec` 대신 심사를 시작한 Registry의 이벤트(record의 ID)가 들어 있다(Step Functions의 `TestState`로 확인했다). 건너뛰기를 넣기 전에는 공유 도구 record도 심사했다. 2026-11-22에 `make seed`가 공유 도구 record(MCP)를 승인 요청 상태로 바꿨을 때 그 심사가 Read에서 `record type is MCP, not AGENT`로 2초 만에 실패하고 알림 단계를 지나 끝났다(그 알림의 내용은 확인하지 않았다). 심사가 실패하면 record는 `PENDING_APPROVAL`에 남는다. 플랫폼팀이 사유를 적어 반려하면 record가 `REJECTED`가 되고, 처음 올리는 에이전트면 심사가 만든 것이 지워진다(아래 "반려"). 승인된 에이전트의 새 버전이면 반려는 아무것도 지우지 않는다. 그때 에이전트가 어떤 상태이고 무엇을 하는지는 아래 "심사가 실패했을 때"에 모았다.

일을 나누는 기준은 하나다. 제출된 코드를 다루는 단계(Scan, Deploy)는 CodeBuild가 하고, 그 역할에는 권한을 주는 action이 없다. Scan의 역할은 제출물을 읽기만 한다. Deploy의 역할은 Runtime을 만들 수 있고(정책은 만들기를 `runtime/*`에 허락한다. IAM이 만들기를 그 자원에 대어 보므로 자원으로는 허브의 이름으로 좁히지 못했다. AWS의 Service Authorization Reference는 두 만들기에 Runtime의 이름으로 거르는 조건 키를 적지 않는다. 아래 "알려진 한계: 배포 단계의 권한"), 허브의 Runtime(`<prefix>_<에이전트>`)을 고치고 읽을 수 있고, Runtime에 이름이 `<prefix>-agent-*-role`인 역할을 넘길 수 있고, Runtime ARN을 SSM에 쓸 수 있다(정책이 허락하는 SSM 값은 `/<prefix>/agents/<에이전트>/runtime_arn`뿐이다). 역할, 정책, target을 만들거나 record를 승인하지는 못한다. 권한을 주는 단계(Read, Grant, Entry, TestCall, Approve)는 Lambda가 하고, 제출된 코드를 열지 않는다. 단계마다 역할이 따로 있다. 남는 한계는 둘이다. 배포 역할 하나가 모든 심사에 쓰이므로, 배포 build 안에서 코드를 실행할 수 있으면 허브의 다른 에이전트의 Runtime을 바꾸거나, 다른 에이전트의 실행 역할을 넘기거나, 다른 에이전트의 코드 묶음(제출함의 `packages/` 아래)을 덮어쓰거나, 다른 에이전트의 `runtime_arn`을 쓸 수 있다(Runtime 버전은 저마다 묶음의 object version을 가리키므로, 덮어써도 이미 만든 버전이 가리키는 묶음은 그대로다. 이것은 AWS에서 아직 돌리지 않았다. Entry는 그 에이전트의 Runtime이 아닌 ARN을 거부한다). 또 정책은 이름이 `<prefix>_`로 시작하지 않는 Runtime의 만들기를 막지 않으므로, 그런 코드가 다른 이름의 Runtime을 만들 길이 열려 있다(실제로 되는지는 해 보지 않았다). 그런 Runtime이 생기면 허브의 정리는 그것을 찾지 못한다. Grant는 이 이름의 역할을 권한 경계를 달아서만 만든다(IAM이 Grant의 역할에 이 조건을 건다). 허브 밖에서 이 이름으로 만든 역할에는 경계가 없을 수 있지만, 그런 역할을 만들려면 계정의 IAM 권한이 있어야 하고 심사의 역할 가운데 그 권한을 가진 것은 없다(아래 "알려진 한계: 배포 단계의 권한").

## 개념도에서의 위치

"호스팅 심사" 상자다. ③ "심사 시작"에서 시작해 ④ "에이전트에 도구 권한 부여"(Grant), ⑤ "에이전트 배포"(Deploy), ⑥ "요청 허용, 승인 표시"(Approve)를 한다. 앞의 Read와 Scan은 상자 안의 "자동 점검"이고, Entry와 TestCall은 그림에 그리지 않았다. 실패하면 ④-1 "심사 실패 알림"(점선)으로 빠진다.

## 일곱 단계

| # | 단계 | 누가 돌리나(역할) | 할 수 있는 일 | 할 수 없는 일 |
|---|---|---|---|---|
| 1 | Read | Lambda `<prefix>-review-read` (`<prefix>-review-read-role`) | 카탈로그의 record를 읽는다(`GetRegistryRecord`). 먼저 심사할 record인지 본다. AGENT가 아닌 record(공유 도구)와 신청서의 `framework`가 `harness`인 record는 `{"skip": "<이유>"}`를 돌려주고, 심사는 `Skipped`로 끝난다(알림 없음). 그다음 같은 record의 심사가 이 심사보다 먼저 시작해 아직 돌고 있는지 본다. state machine이 Read에 Registry의 이벤트와 이 실행의 ARN과 state machine의 ARN을 넘긴다. Read의 역할은 record를 읽고(`GetRegistryRecord`), 같은 record의 앞선 심사를 찾으려고 이 state machine의 실행을 나열하고 그 입력을 읽는다(`states:ListExecutions`, `states:DescribeExecution`). 바꾸는 것은 없다. 앞선 심사가 있으면 `a review of this record is already running: <실행 이름>`으로 멈추고 알림으로 빠진다(아래 "승인된 에이전트의 새 버전"). 나머지 record는 신청서를 확인한다. 신청서의 이름이 record의 이름과 같아야 한다. 뒤의 단계는 신청서의 이름으로 만들고, 반려와 정리는 record의 이름으로 찾기 때문이다. 팀과 프레임워크는 64자까지의 문자열, 도구는 목록, 코드는 `submissions/` 아래의 key와 문자열 version이어야 한다. 이름에서 만드는 정책 이름이 한도에 맞는지도 본다(아래 "정책 이름"). 다음 단계에는 확인한 칸(이름, 팀, 프레임워크, 도구, 코드의 key와 version)만 넘긴다. | 제출된 코드 읽기, record 바꾸기, 정책 만들기, 심사를 시작하거나 멈추기, 다른 state machine의 실행 읽기 |
| 2 | Scan | CodeBuild `<prefix>-review-scan` (`<prefix>-review-scan-role`) | 신청서에 적힌 version의 제출물과 허브의 코드 묶음을 읽는다. 압축을 풀어 모양과 `requirements.txt`를 확인하고, 규칙에 맞는 줄을 플랫폼의 파일(`/tmp/audit/requirements.txt`)에 다시 써서 그 파일을 `pip-audit`(2.10.1로 고정)로 검사한다. 배포가 설치하는 줄과 같은 줄이다(아래 "`requirements.txt` 규칙"). 자기 build 로그를 쓴다. | 이것 말고는 모두. 역할, 정책, target, record, SSM에 손댈 수 없다. |
| 3 | Grant | Lambda `<prefix>-review-grant` (`<prefix>-review-grant-role`) | 에이전트의 실행 역할(`<prefix>-agent-<에이전트>-role`)을 권한 경계 `<prefix>-agent-boundary`를 달아서 만들고, 신청서에 적힌 도구마다 도구 게이트웨이에 `tool_<에이전트>_<Target>_<도구>`를 건다. 그 에이전트의 도구 정책 가운데 신청서에 없는 도구의 것(승인된 이전 버전이 받은 것)은 그 전에 지운다. 이름의 모양으로 찾으므로 다른 에이전트의 정책은 건드리지 않는다. 같은 정책 목록에서 그 에이전트의 `entry_permit_<에이전트>`가 이미 있는지 보고 심사의 상태(`entryPermitBefore`)에 적는다. 이 정책은 Approve만 만들고 Approve는 Grant 뒤에 돌므로, 이 값은 이 심사 전에 있었는지다. 실행 역할이 부를 수 있는 모델은 허브의 `MODEL_ID` 하나이고, 토큰을 받을 수 있는 workload identity는 그 에이전트의 Runtime의 것(`<Runtime 이름>-*`)뿐이다. trace는 X-Ray로 보낼 수 있고, 메트릭은 namespace `bedrock-agentcore`에만 쓸 수 있다(아래 "에이전트 실행 역할의 상한"). | 경계 없이 역할 만들기, 경계를 바꾸거나 떼기, 에이전트 게이트웨이에 정책 걸기, 다른 이름의 역할 만들기, 제출된 코드 읽기 |
| 4 | Deploy | CodeBuild `<prefix>-review-deploy` (`<prefix>-review-deploy-role`) | 제출물과 허브의 코드 묶음을 읽고, 의존성을 Runtime의 플랫폼용 wheel로 받아 제출된 `.py` 파일과 함께 묶는다(아래 "배포 build가 하는 일"). 묶음을 제출함의 `packages/` 아래에 쓰고(Runtime에는 그 묶음의 object version까지 넘긴다), Runtime 목록에서 `<prefix>_<에이전트>`를 찾아 없으면 만들고(`CreateAgentRuntime`) 있으면 고친다(`UpdateAgentRuntime`). 그 Runtime에 Grant가 만든 실행 역할(`ROLE_ARN`)을 넘긴다. 정책이 허락하는 것은 이름이 `<prefix>-agent-*-role`인 역할을 AgentCore에 넘기는 것이다(`iam:PassRole`). Runtime ARN을 SSM `/<prefix>/agents/<에이전트>/runtime_arn`에 쓴다. 정책이 허락하는 SSM 값은 이 모양의 이름뿐이다. | 역할이나 정책 만들기, target 만들기, record 승인하기, 이름이 `<prefix>_`로 시작하지 않는 Runtime을 고치거나 읽기(그런 Runtime을 만드는 것은 정책이 막지 않는다. 실제로 되는지는 해 보지 않았다), 이름이 `<prefix>-agent-*-role`이 아닌 역할 넘기기, `/<prefix>/agents/<에이전트>/runtime_arn`이 아닌 SSM 값 쓰기. 아래의 한계를 보라. |
| 5 | Entry | Lambda `<prefix>-review-entry` (`<prefix>-review-entry-role`) | SSM에서 Runtime ARN을 읽고, 그 ARN이 이 에이전트의 Runtime(이 계정과 리전의 `runtime/<Runtime 이름>-<ID 10자>`)인지 확인한다. 배포 역할은 어느 에이전트의 `runtime_arn`이든 쓸 수 있기 때문이다. 맞으면 에이전트 게이트웨이에 그 에이전트의 target을 만든다. target을 만들 때 읽을 수 있는 Runtime은 이름이 `<prefix>_`로 시작하는 것뿐이다(배포 단계가 만드는 이름). 같은 이름의 target이 이미 있으면 그 target이 같은 Runtime을 가리킬 때만 그대로 쓴다. 시험 호출만 들어오게 하는 `review_permit_<에이전트>`와 비밀값을 막는 `guard_secret_<에이전트>`를 건다. | 도구 게이트웨이에 정책 걸기, record 승인, 제출된 코드 읽기 |
| 6 | TestCall | Lambda `<prefix>-review-testcall` (`<prefix>-review-testcall-role`) | 에이전트 게이트웨이로 에이전트를 두 번 부른다. 보통 질문에는 답이 와야 하고, 예시 access key가 든 질문은 거부(403)돼야 한다. 승인 전에 들어올 수 있는 것은 이 역할뿐이다. | 에이전트 게이트웨이를 부르는 것 말고는 모두 |
| 7 | Approve | Lambda `<prefix>-review-approve` (`<prefix>-review-approve-role`) | record를 다시 읽어 Read와 같은 확인을 거치고, 신청서 전체가 심사를 시작할 때와 같은지, record가 아직 승인 요청 상태(`PENDING_APPROVAL`)인지 확인한다. 그러면 플랫폼팀이 켜 둔 전사 정책을 그 모드 그대로 건다. 켜진 전사 정책과 모드는 SSM `/<prefix>/policies/` 아래에서 읽는다(`ssm:GetParametersByPath`. 정책이 허락하는 SSM 읽기는 경로 `/<prefix>/policies`의 이 action뿐이다). 그다음 사용자가 들어오게 하는 `entry_permit_<에이전트>`를 걸고, 같은 확인을 한 번 더 한 뒤 record를 `APPROVED`로 바꾼다. 그사이에 신청서가 바뀌었거나 record가 반려되었으면 승인하지 않고 알림으로 빠진다. `entry_permit_<에이전트>`를 걸기 시작한 뒤에 실패하면(그 정책의 기다림, 두 번째 확인, `APPROVED`로 바꾸는 호출) 이번 심사에서 건 `entry_permit_<에이전트>`를 이름으로 찾아 지운 뒤 알림으로 빠진다. 이 심사 전부터 있던 것(승인된 이전 버전의 것)은 그대로 둔다. 전부터 있었는지는 Grant가 적은 `entryPermitBefore`로 안다. 그래서 Step Functions가 Approve를 다시 불러도(같은 입력이다) 앞의 시도가 건 정책을 이번 심사의 것으로 알고 지운다. 입력에 이 값이 없으면 Approve는 아무것도 만들지 않고 멈춘다. `APPROVED`로 바꾸는 호출이 실제로는 됐는데 답을 잃었다면, record는 `APPROVED`인데 `entry_permit_<에이전트>`가 없어 사용자가 거부된다. 다시 제출하면 고쳐진다(코드로 보면 그렇다. AWS에서는 해 보지 않았다). 지우기가 실패하면 그 실패를 승인하지 않은 이유와 함께 알린다. 그사이에 건 전사 정책은 남는다. 막는 정책이라 남아도 아무도 들이지 않는다. 남은 것은, 이 심사 전에 `entry_permit_<에이전트>`가 없던 에이전트(처음 올리는 에이전트)면 반려가 지운다. 있던 에이전트(승인된 에이전트의 새 버전)면 반려는 아무것도 지우지 않는다(아래 "심사가 실패했을 때"). record가 반려되었으면 반려를 한 번 더 돌린다. 팀이 record를 고쳐 `DRAFT`가 되었으면 반려가 상태를 그대로 두고 지운다(아래 "반려"). 이 역할에는 정책의 적용 모드를 바꾸는 권한(`UpdatePolicy`)이 없고, Approve는 모드를 바꾸지 않는다. 그 에이전트에 같은 이름의 전사 정책이 다른 모드로 이미 있으면 그 정책을 그대로 두고, `entry_permit_<에이전트>`를 걸지 않고 실패해 알림으로 빠진다. 심사 중에 rollout이 그 에이전트에 정책을 건 뒤, 모드를 바꾸는 rollout이 그 에이전트에서 실패했거나 아직 그 에이전트에 이르지 않았을 때다. 모드는 rollout이 맞춘다(코드가 그렇게 한다. AWS에서는 해 보지 않았다). 2026-11-22의 운영 확인에서는 `guard_prompt`를 적용 모드로 켠 뒤에 승인된 `docs_adk`에 Approve가 이 역할로 SSM을 읽고 `guard_prompt_docs_adk`를 적용 모드로 걸었다(심사의 상태 `companyPolicies`가 `{"guard_prompt": "ACTIVE"}`). 같은 모드의 정책이 이미 있던 `quality_agent`의 새 버전 둘에서는 그 정책을 그대로 썼다. 전사 정책은 `company_policy/README.md`의 "전사 정책 켜고 끄기"에 있다. | 바뀐 record나 승인 요청 상태가 아닌 record 승인하기, 정책의 적용 모드 바꾸기, `/<prefix>/policies` 밖의 SSM 값 읽기, 도구 게이트웨이에 정책 걸기, 역할 만들기, 제출된 코드 읽기 |

심사 밖에서 에이전트 실행 역할과 도구 정책을 만드는 곳이 하나 더 있다. 처음부터 올라와 있는 harness 에이전트(`dev_team/preloaded_agents/spec_assistant`)는 코드가 없어 심사가 건너뛰므로, `make preload`(`preload_agents.host_harness`)가 Grant가 에이전트 역할을 만드는 함수(`review_steps.ensure_agent_role`, 권한은 `_execution_role`)로 같은 권한 경계를 달아 그 에이전트의 실행 역할을 만들고, 신청서의 도구마다 Grant와 같은 도구 정책을 건다. 그리고 harness를 만들고 record를 승인한다. 그 이름의 harness가 이미 있으면 harness와 그 실행 역할, 도구 정책을 그대로 두고 다시 쓰지 않는다(Grant와 다르다. `agent.json`이나 `MODEL_ID`가 바뀌었어도 같다). 이 일은 심사의 역할이 아니라 `make preload`를 돌리는 플랫폼팀의 자격 증명으로 한다. 처음부터 올라와 있는 다른 에이전트 `docs_adk`는 코드가 있어 위의 일곱 단계를 그대로 거친다.

Lambda 단계는 모두 자기 로그만 쓸 수 있다. 정책을 만드는 단계(Grant, Entry, Approve)는 policy engine에서 정책을 만들고 읽고 지울 수 있고, 그 정책이 가리키는 게이트웨이 하나에만 그 게이트웨이를 확인하는 권한(`ManageResourceScopedPolicy`, `GetGateway`, `ListGatewayTargets`, `GetGatewayTarget`, `InvokeGateway`)을 갖는다. 정책이 게이트웨이를 가리키면 정책을 만드는 쪽에 이 권한이 있어야 한다는 것은 실행해서 찾았다.

Lambda 단계는 제한 시간(가장 길어도 900초)에 끊기기 전에 스스로 멈춘다. 처리기가 제한 시간 60초 전을 마감으로 정하고, 단계의 기다림(정책 하나에 300초, target에 300초, 시험 호출의 재시도)은 저마다의 한도와 마감까지 남은 시간 가운데 짧은 쪽만 기다린다. 마감까지 정책이 `ACTIVE`가 되지 않으면 그 정책을 지우고, 알림에는 Lambda의 시간 초과가 아니라 단계가 낸 오류가 간다.

지휘하는 역할도 둘 있다. state machine의 역할 `<prefix>-sfn-role`은 다섯 Lambda를 부르고, 두 CodeBuild 프로젝트를 시작하고 기다리고, 알림 주제에 보내고, 실행 로그를 쓴다. rule의 역할 `<prefix>-events-role`은 이 state machine을 시작하는 것만 한다.

## 정책 이름

심사는 에이전트마다 네 가지 정책을 만든다. 플랫폼팀이 켜 둔 전사 정책(지금은 `guard_prompt_<에이전트>`)이 있으면 Approve가 그것도 건다. 이름은 `platform_team/company_policy/policy_names.py` 한 곳에서 만들고, 신청서 검사, 심사 단계, 반려가 모두 이 파일을 쓴다.

| 이름 | 만드는 단계 | 하는 일 |
|---|---|---|
| `tool_<에이전트>_<Target>_<도구>` | Grant | 에이전트가 이 도구를 부를 수 있다(도구 게이트웨이). |
| `review_permit_<에이전트>` | Entry | 승인 전에는 심사의 시험 호출만 에이전트를 부를 수 있다. |
| `guard_secret_<에이전트>` | Entry | 비밀값이 든 질문을 거부한다. |
| `guard_prompt_<에이전트>` | 운영, Approve | 프롬프트 공격(`PROMPT_INJECTION`, 신뢰도 0.4 초과)인 질문을 거부한다. 전사 정책이다. 플랫폼팀이 `company_policy/rollout.sh`로 모든 에이전트에 켜고 끈다. 켜져 있으면 Approve가 새 에이전트에 같은 모드로 건다. 반려와 삭제가 지운다. |
| `stop_agent_<에이전트>` | 운영 | 심사의 시험 호출 말고는 그 에이전트의 모든 호출을 거부한다. 플랫폼팀이 `agent_stop/stop.sh`로 걸고 `agent_stop/resume.sh`로 지운다(`agent_stop/README.md`). 심사는 만들지 않는다. 반려와 삭제도 지운다. |
| `entry_permit_<에이전트>` | Approve | 사용자가 에이전트를 부를 수 있다. |

예를 들면 `tool_quality_agent_Quality_get_inspection_data`(46자), `review_permit_release_review`(28자)다.

한 이름은 한 종류, 한 에이전트, 한 도구의 것이다. 종류의 앞부분(`tool_`, `review_permit_`, `guard_secret_`, `guard_prompt_`, `stop_agent_`, `entry_permit_`)은 어느 것도 다른 것의 앞부분이 아니다. 에이전트 이름은 소문자로 시작하는 소문자와 숫자의 마디를 밑줄 하나로 이은 것이다(`quality_agent`, 3~31자). 카탈로그의 target 이름은 대문자로 시작하고 밑줄이 없다(`Quality`). 그래서 도구 정책의 이름에서 에이전트 이름은 첫 대문자 앞에서 끝난다. 같은 규칙 덕분에 에이전트 이름으로 만드는 Runtime 이름(`<prefix>_<에이전트>`, 예: `hub_quality_agent`)과 target 이름(CamelCase, 예: `QualityAgent`)도 에이전트마다 다르다.

policy engine은 정책 이름을 48자까지 받는다. 신청서 검사는 한도를 넘는 정책 이름이 생기는 신청서를 거부하고, 에이전트 이름이 몇 자까지 될 수 있는지 알려 준다. Runtime 이름은 AgentCore가 48자까지 받는다(`CreateAgentRuntime`의 서비스 모델, `[a-zA-Z][a-zA-Z0-9_]{0,47}`). 접두어(10자까지)와 밑줄과 에이전트 이름(31자까지)을 이어도 42자이므로 따로 검사하지 않는다(`tests/test_config.py`가 확인한다). 검사는 제출할 때(`publish.sh`)와 심사의 Read 단계에서 돌므로, 넘는 이름으로는 아무것도 만들어지지 않는다. 이름을 자르거나 바꾸지 않는다. 이름은 나중에 화면에 그대로 보인다.

## 제출함

S3 bucket `<prefix>-<account>-<region>`이다. 버전 관리를 켜 두었다. bucket 정책은 TLS로 오지 않은 요청을 모두 거부한다(`aws:SecureTransport`가 `false`면 `Deny`). 이 정책을 단 허브에서 2026-11-22의 `make e2e`(12개 통과)가 제출, 두 build, Runtime 만들기를 모두 마쳤다. TLS가 아닌 요청이 거부되는지는 보내 보지 않았다. 개발팀 역할(`dev_access`)은 `submissions/` 아래에 올릴 수 있다(`s3:PutObject`). 신청서에는 올린 object의 version을 적고, Scan과 Deploy는 꼭 그 version을 읽는다. 그래서 검사한 코드와 올리는 코드가 같다. 허브의 코드 묶음(`build/platform_team.zip`)은 Terraform이 `platform/platform_team.zip`에 올려 두고, 두 build가 내려받아 `submission_check.py`와 `deploy_build.py`를 돌린다. 배포 build는 에이전트의 코드 묶음을 `packages/<에이전트>/<code version>.zip`에 쓴다. Runtime의 코드 위치(`agentRuntimeArtifact`)가 이 묶음이고, 묶음을 올린 호출이 돌려준 object version(`versionId`)까지 적는다. 그래서 같은 key에 묶음을 다시 써도 이미 만든 Runtime 버전은 저마다 제 version을 가리킨다. 서비스 모델(botocore 1.44.9)의 `CreateAgentRuntime`과 `UpdateAgentRuntime`은 코드 위치에 `versionId`를 받고, 없으면 그 key의 최신 version을 쓴다고 적는다. version을 적는 것은 AWS에서 아직 돌리지 않았다.

## 배포 build가 하는 일

`buildspec_deploy.yml`은 Python 3.13과 uv(0.10.8로 고정)만 설치하고 `deploy_build.py`를 돌린다. 개발 팀이 내는 것은 코드(`main.py`와 그 밖의 `.py` 파일)와 `requirements.txt`뿐이고, 무엇을 설치하고 Runtime을 어떻게 돌릴지는 플랫폼이 정한다. `deploy_build.py`가 아래 순서로 한다.

1. 제출물을 카탈로그 기록에 적힌 object version으로 S3에서 받아 푼다. 위험한 경로가 있거나, `main.py`나 `requirements.txt`가 없거나, `requirements.txt`가 아래 규칙에 맞지 않으면 멈춘다.
2. 제출물에 있는 `pyproject.toml`, `uv.lock`, `uv.toml`, `.python-version`은 거부하지 않고 지운다. buildspec도 `UV_NO_CONFIG=1`을 두어 uv가 설정 파일을 하나도 읽지 않게 한다. `requirements.txt`의 줄은 플랫폼이 자기 파일에 다시 쓰고, uv는 그 파일을 읽는다. 검사 단계가 검사한 파일을 쓴 함수(`submission_check.requirements_from`)로 쓰므로 줄이 같다.
3. `uv pip install --only-binary :all: --python-platform aarch64-manylinux2014 --python-version 3.13 --target <폴더>`로 의존성을 Runtime의 플랫폼(Linux arm64, CPython 3.13)용 wheel로만 받는다.
4. 받은 파일과 제출물의 맨 위 `.py` 파일을 zip 하나로 묶는다(`__pycache__`는 빼고, 이름 순서로). 하위 폴더와 `.py`가 아닌 파일은 넣지 않는다. 묶음을 `packages/<에이전트>/<code version>.zip`에 올리고, 그 호출이 돌려준 object version(`VersionId`)을 받는다.
5. Runtime 목록(모든 페이지)에서 `<prefix>_<에이전트>`를 찾는다. 없으면 `CreateAgentRuntime`으로 만들고, 있으면 `UpdateAgentRuntime`으로 고친다. 넘기는 값은 묶음의 위치와 그 object version(`versionId`), `PYTHON_3_13`, 진입점 `["opentelemetry-instrument", "main.py"]`(`main.py`를 OpenTelemetry로 감싸 띄워 trace를 내게 한다. [모니터링](../agent_monitoring/README.md#에이전트의-trace)), Grant가 만든 실행 역할(`ROLE_ARN`), 공개 네트워크, HTTP, 환경 변수 넷(`HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME`)이다. 방금 만든 실행 역할은 바로 쓰이지 않을 수 있으므로, 만들기가 `ValidationException`이나 `AccessDeniedException`으로 실패하면 15초 간격으로 여덟 번까지 해 본다. 메시지에 `is not authorized to perform: bedrock-agentcore:`나 `is not authorized to perform: iam:PassRole`이 있으면 배포 역할 자신에게 그 권한이 없는 것이므로 다시 하지 않는다.
6. 만들거나 고친 호출이 돌려준 버전(`agentRuntimeVersion`)이 `GetAgentRuntime`에서 `READY`가 될 때까지 기다린다(900초까지). 다른 버전이 `READY`로 보이는 동안은 기다린다. 상태가 `…FAILED`로 끝나면 Runtime의 `failureReason`을 말하고 멈춘다.
7. Runtime ARN을 SSM `/<prefix>/agents/<에이전트>/runtime_arn`에 쓴다. 다음 단계(Entry)가 이 값을 읽는다.

## `requirements.txt` 규칙

`requirements.txt`에는 패키지 색인에 있는 패키지를 이름으로 적는다. 쓸 수 있는 것은 이름, extras, 버전뿐이다. 검사 단계는 다음을 거부한다.

- pip 옵션(`-r`, `-e`, `--index-url`, `--hash`)
- 직접 참조(`pkg @ URL`, URL, `file:`, 로컬 경로)
- 환경 표시(`; python_version >= "3.10"`, `; platform_release == ""` 같은 것). 검사 단계의 pip는 환경 표시를 검사하는 기계에 대어 보고, 배포의 uv는 Runtime 대상(Linux aarch64, CPython 3.13)에 대어 본다. 그래서 검사에서는 빠지고 배포에서는 설치되는 줄이 생길 수 있다. 대상이 하나로 정해져 있으니 환경 표시는 쓸 일이 없다.

배포 build는 같은 규칙(`submission_check.parse_requirements`)으로 한 번 더 확인한다.

검사 단계는 팀의 `requirements.txt`를 그대로 검사하지 않는다. `submission_check.py`가 규칙에 맞는 줄을 주석, 빈 줄, 이어 쓰기(`\`)를 없애고 한 줄에 하나씩 플랫폼의 파일에 다시 쓰고(`requirements_from`), `pip-audit`는 그 파일을 검사한다. 배포 build도 같은 함수로 쓴 파일로 설치한다. 그래서 검사한 줄과 설치하는 줄이 같다. 전에는 `pip-audit`가 팀의 파일을 직접 읽었다. `pip-audit`(2.10.1)와 pip(26.3)는 `\`로 끝나는 주석 줄을 다음 줄과 잇지 않는데 플랫폼의 규칙은 잇는다. 그래서 그런 주석 다음 줄의 패키지는 검사에는 들어가고 설치에서는 빠졌다(두 parser의 결과는 로컬에서 확인했다. 같은 줄이 되는 것은 `tests/test_submission.py`가 확인한다).

그래서 `requirements.txt`에 적힌 패키지는 검사 단계가 모두 검사하고, 배포가 모두 설치한다. 두 단계 모두 기본 색인(PyPI)에서 wheel만 받고, sdist의 `setup.py`는 실행하지 않는다. 다만 버전을 범위로 적으면 두 단계가 따로 고르므로, `==`로 고정해야 검사한 버전과 같아진다.

간접 의존성은 이렇게 보장되지 않는다. 두 단계가 따로 고르므로, 그 사이에 새 버전이 나오거나 어떤 패키지의 의존성에 환경 표시가 있으면 배포가 설치하는 것이 검사한 것과 다를 수 있다. 운영 환경이라면 검사 단계가 배포 대상에 맞춰 `uv pip compile`로 간접 의존성까지 고정한 목록을 만들어 검사하고, 배포는 그 목록을 그대로 설치하게 한다.

## 에이전트 실행 역할의 상한(권한 경계)

Grant의 역할은 IAM 역할을 만들고 그 inline 정책을 쓸 수 있다. IAM은 inline 정책의 내용을 조건으로 막지 못하므로, 경계가 없다면 이 단계는 무엇이든 할 수 있는 역할을 만들 수 있다. 그래서 Grant는 권한 경계 `<prefix>-agent-boundary`가 달린 역할에만 `CreateRole`과 `PutRolePolicy`를 할 수 있다(`iam:PermissionsBoundary` 조건). 경계를 바꾸거나 떼는 권한은 없다. 경계는 에이전트 실행 역할에 필요한 것의 상한이다. 그 내용은 Runtime 로그, 도구 게이트웨이 호출, 모델 호출(inference profile과 foundation model), workload identity의 토큰, trace 보내기(X-Ray), 메트릭 쓰기(namespace `bedrock-agentcore`에만)다. `make preload`가 harness 에이전트에 만드는 역할도 같은 함수와 같은 경계로 만든다. 그 역할의 workload identity 권한(`<Runtime 이름>-*`, 곧 `<prefix>_<에이전트>-*`)은 harness의 workload identity와 맞지 않는다. 2026-11-22의 실행에서 harness의 것은 `harness_<prefix>_<에이전트>-<10자>`였다(harness가 도는 Runtime의 ID). 그 실행에서 harness는 이 권한 없이 모델과 도구 게이트웨이를 불렀다. 역할의 실제 권한은 inline 정책과 경계가 함께 허용하는 것뿐이다. 그래서 inline 정책에 무엇이 들어가도 역할은 이 상한을 넘지 못한다. 경계가 실행 역할의 action을 모두 허용하는지는 단위 시험이 확인한다(`tests/test_review_iam.py`).

Grant가 쓰는 inline 정책(`review_steps._execution_role`)은 경계보다 좁다. 모델은 허브의 `MODEL_ID` 하나만 부를 수 있다. 추론 프로파일(`us.anthropic.…`)이면 허브의 리전과 계정의 그 프로파일과, 그 뒤의 foundation model(어느 리전이든)이다. 그 밖의 ID는 허브의 리전의 foundation model로 본다. workload identity의 토큰(`GetWorkloadAccessToken…`)은 그 에이전트의 Runtime의 것만 받을 수 있다. Runtime의 workload identity는 이름이 Runtime ID(`<Runtime 이름>-<10자>`)와 같으므로 자원은 `workload-identity-directory/default/workload-identity/<Runtime 이름>-*`이다. AWS 문서의 Runtime 실행 역할 예시([IAM Permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)의 `GetAgentAccessToken`)가 같은 모양(`…/workload-identity/agentName-*`)이다. 에이전트 이름에는 `-`가 없으므로 다른 에이전트의 것과 겹치지 않는다. 2026-11-22의 실행에서 두 에이전트의 실행 역할이 이 정책으로 모델(기본값의 추론 프로파일)을 불렀다. CloudTrail의 이벤트 기록에 `release_review`의 `Converse` 3번과 `quality_agent`의 `ConverseStream` 4번이 오류 없이 남았다. workload identity의 토큰을 받는 호출은 그 기록에 하나도 보이지 않았으므로, 토큰의 자원을 좁힌 것은 이 실행으로 확인되지 않았다.

trace와 메트릭의 권한은 같은 예시에서 그대로 옮겼다(2026-11-22에 읽었다). X-Ray의 네 action(`PutTraceSegments`, `PutTelemetryRecords`, `GetSamplingRules`, `GetSamplingTargets`)은 `"*"`에 준다. AWS의 Service Authorization Reference가 이 action들에 자원 종류를 두지 않으므로 `"*"`만 맞는다. 조건 키는 찾아보지 않았다(같은 Reference는 `xray:PutTraceSegments`에 조건 키 `logs:LogGeneratingResourceArns`를 적는다. 그것으로 좁혀지는지는 해 보지 않았다). `cloudwatch:PutMetricData`도 예시처럼 `"*"`에 주고, 조건(`cloudwatch:namespace`)으로 namespace `bedrock-agentcore`에만 쓰게 한다. 실행 역할에서 `"*"`에 걸린 것은 이 둘뿐이다(`tests/test_review_steps.py`). 그래서 정책으로는 에이전트의 코드가 X-Ray에 어떤 서비스 이름으로든 trace를 쓸 수 있고, namespace `bedrock-agentcore`에는 계정의 다른 에이전트가 쓰는 메트릭과 같은 이름으로도 쓸 수 있다. 정책이 그렇게 허락한다는 것이고, 해 보지는 않았다. 예시에는 에이전트의 로그 그룹에 대한 `logs:PutResourcePolicy`도 있다. AgentCore 개발자 안내서는 X-Ray가 span을 에이전트의 로그 그룹에 넣게 하려고 이 권한을 쓴다고 적는다. 이것은 넣지 않았다. 권한을 바꾸는 action이고, 같은 Reference가 이 action에도 자원 종류를 두지 않아 로그 그룹 자원으로 좁혀지지 않을 수 있기 때문이다. 이 권한 없이 span이 어디에 남았는지는 [모니터링](../agent_monitoring/README.md#에이전트의-trace)에 적었다.

## 알려진 한계: 배포 단계의 권한

배포 단계는 제출된 코드를 묶어 AgentCore의 API(`CreateAgentRuntime`, `UpdateAgentRuntime`)를 직접 부른다. 다른 역할을 맡지 않으므로, 배포 build가 AWS에서 할 수 있는 것은 배포 역할의 정책(`terraform/iam.tf`의 `deploy`)에 적힌 것뿐이다. 자기 build 로그 쓰기, 제출물과 허브의 코드 묶음 읽기, 제출함의 `packages/` 아래에 묶음 쓰고 읽기(object version을 정한 읽기 `s3:GetObjectVersion`도. Runtime이 묶음을 version으로 가리키므로, 서비스가 배포 역할의 권한으로 묶음을 읽는다면 이 권한이 필요하다. 이것은 AWS에서 아직 돌리지 않았다), Runtime과 그 endpoint 만들기(자원은 `runtime/*`, 아래), 이름이 `<prefix>_`로 시작하는 Runtime을 고치고 읽기와 그 endpoint를 읽기, 이름이 `<prefix>_`로 시작하는 workload identity(`workload-identity-directory/default` 아래)를 만들고 읽기, 계정의 Runtime 목록 읽기, 이름이 `<prefix>-agent-*-role`인 역할을 AgentCore에만 넘기기, Runtime ARN을 SSM에 쓰기(`/<prefix>/agents/<에이전트>/runtime_arn`, 정책이 허락하는 SSM 값은 이 이름의 것뿐이다)다. 역할, 정책, target을 만들거나 record를 승인하는 action은 없다.

Runtime 목록(`ListAgentRuntimes`)은 IAM에서 자원으로 좁히지 않았다. AWS의 Service Authorization Reference가 이 action에 자원 종류를 두지 않으므로 `"*"`만 맞는다. `"*"`로 되는 것은 2026-11-22의 실행에서 봤고, 더 좁힌 자원은 해 보지 않았다. 그래서 배포 역할은 계정에 있는 모든 Runtime의 이름, ID, ARN, 버전, 설명, 상태를 읽을 수 있다. 목록을 읽기만 하고, 이름이 `<prefix>_`로 시작하지 않는 Runtime을 읽거나(`GetAgentRuntime`) 바꾸지는 못한다.

Runtime 만들기(`CreateAgentRuntime`)는 자원(ARN)으로 이름을 좁히지 못했다. 처음에는 `runtime/<prefix>_*`로 좁혔는데, 2026-11-22의 실행에서 IAM이 이 action을 `runtime/*`에 대어 보고 거부했다(`is not authorized to perform: bedrock-agentcore:CreateAgentRuntime on resource: arn:aws:bedrock-agentcore:<region>:<account>:runtime/*`). 만들 때는 아직 Runtime의 ID가 없기 때문으로 보이지만, 이유는 확인하지 않았다. 다음 build에서는 만들기가 함께 하는 endpoint 만들기(`CreateAgentRuntimeEndpoint`)가 같은 모양으로 거부됐다(`on resource: …:runtime/*`). 그래서 이 두 action만 따로 `runtime/*`에 둔다(`CreateTheRuntime`). 이 문장은 만들기를 허브의 이름으로 묶지 않으므로, 정책으로만 보면 어떤 이름의 Runtime이든 만들 길이 열려 있다. 이름이 `<prefix>_`로 시작하지 않는 Runtime을 만들어 보지는 않았다. 만든 Runtime마다 Runtime ID와 같은 이름의 workload identity가 생겼고, 배포 역할의 workload identity 권한(`CreateWorkloadIdentity`)은 이름이 `<prefix>_`로 시작하는 것에만 닿는다. 그래서 다른 이름의 만들기가 되는지는 모른다. 조건 키는 AWS의 Service Authorization Reference([Actions, resources, and condition keys for Amazon Bedrock AgentCore](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrockagentcore.html), 2026-11-22에 읽었다)에 이렇게 적혀 있다. `CreateAgentRuntime`에는 자원 종류가 없고 조건 키는 `aws:RequestTag/${TagKey}`, `aws:TagKeys`, `bedrock-agentcore:RuntimeAuthorizerType`, `bedrock-agentcore:securityGroups`, `bedrock-agentcore:subnets`다. `CreateAgentRuntimeEndpoint`에는 자원 종류 `runtime`(`runtime/${RuntimeId}`)이 있고 조건 키는 `aws:RequestTag/${TagKey}`, `aws:ResourceTag/${TagKey}`, `aws:TagKeys`다. 그 페이지의 조건 키 표에는 Runtime의 이름으로 거르는 키가 없다. 그래서 조건 키로도 만들기를 허브의 이름에 묶을 수 없다. 태그의 키로는 만들 때 정한 태그를 붙이라고 요구할 수 있지만 허브는 그것을 쓰지 않는다. 그런 조건은 이름을 묶지 않고, 같은 역할로 도는 배포 build 안의 코드도 그 태그를 붙일 수 있다(정책으로 보면 그렇다). 페이지를 읽기만 했고 AWS에서 확인하지 않았다. 만든 Runtime에 넘길 수 있는 역할은 이름이 `<prefix>-agent-*-role`인 것뿐이다.

남는 한계는 둘이다. 첫째, 배포 역할 하나가 모든 심사에 쓰인다. 그래서 배포 build 안에서 코드를 실행할 수 있으면 허브의 다른 에이전트의 Runtime을 바꾸거나(다른 코드, 다른 환경 변수), 다른 에이전트의 실행 역할을 넘기거나, 다른 에이전트의 코드 묶음(제출함의 `packages/` 아래)을 덮어쓰거나, 다른 에이전트의 `runtime_arn`을 쓸 수 있다. 그 값은 Entry가 그 에이전트의 Runtime ARN인지 확인하고, 아니면 target을 만들지 않는다. 덮어쓴 묶음은 같은 key의 새 object version이 된다. Runtime 버전은 저마다 그것을 만든 배포 build가 쓴 object version을 가리키고(`versionId`), 배포 역할에는 object version을 지우는 권한이 없으므로, 이미 만든 Runtime 버전이 가리키는 묶음은 그대로다. 덮어쓴 묶음이 Runtime에 닿으려면 그 Runtime을 고쳐야 하고, 그것은 바로 앞의 한계(다른 에이전트의 Runtime을 바꾸는 것)다. version을 가리키는 것은 AWS에서 아직 돌리지 않았다. 넘길 수 있는 것은 이름이 `<prefix>-agent-*-role`인 역할이면 어느 것이든이다. Grant는 이 이름의 역할을 권한 경계를 달아서만 만든다(IAM이 Grant의 역할에 이 조건을 건다). 그래서 Grant가 만든 역할을 넘기는 한 경계(위의 "에이전트 실행 역할의 상한") 밖의 권한은 생기지 않는다. 허브 밖에서 이 이름으로 만든 역할에는 경계가 없을 수 있고, 그 역할이 AgentCore를 믿으면 넘길 수 있으며 그 권한은 경계에 묶이지 않는다. 그런 역할을 만들려면 계정의 IAM 권한이 있어야 하고, 심사의 역할 가운데 그 권한을 가진 것은 없다. 다만 도구 정책은 에이전트의 실행 역할을 가리키므로, 다른 에이전트의 역할로 도는 Runtime은 그 에이전트에게 허락된 도구를 부를 수 있다. 둘째, 정책은 이름이 `<prefix>_`로 시작하지 않는 Runtime의 만들기를 막지 않는다(위의 `CreateAgentRuntime`). 그래서 배포 build 안에서 코드를 실행할 수 있으면 그런 Runtime을 만들 길이 열려 있다. 실제로 되는지는 해 보지 않았다(위의 workload identity 권한 때문에 안 될 수도 있다). 그런 Runtime이 생기면 그것도 `<prefix>-agent-*-role` 역할로만 돌 수 있지만, 허브의 정리(`reject`, `make destroy`)는 이름 `<prefix>_<에이전트>`로 찾으므로 그 Runtime을 지우지 않는다. `e2e_checks/check_cleanup.py`도 허브가 쓰는 이름의 모양(`<prefix>_`, `<prefix>-` 같은)으로 찾으므로, 그 모양이 아닌 이름의 Runtime은 보지 못한다.

지금 배포 build를 지키는 것은 제출된 파일이 그 안에서 실행되지 않게 하는 장치다. 의존성은 wheel만 받으므로(`--only-binary :all:`) sdist의 `setup.py`가 돌지 않는다. uv가 읽는 목록은 플랫폼이 `requirements.txt`의 줄을 다시 써서 만든 파일이다. 제출물에 든 `pyproject.toml`, `uv.lock`, `uv.toml`, `.python-version`은 지우고, uv는 설정 파일을 하나도 읽지 않는다(`UV_NO_CONFIG=1`). 제출된 `.py` 파일은 묶음에 들어갈 뿐 build 안에서 import되거나 실행되지 않는다. 이 장치에 틈이 생기면 위의 한계가 드러난다. 제출물에 심은 `uv.toml`이 쓰이지 않는 것은 AgentCore CLI로 배포하던 때 실제 build로 확인했다. 지금의 배포 build로는 `uv.toml`을 심은 제출물을 AWS에서 돌려 보지 않았다.

운영 환경이라면 심사마다 그 에이전트의 Runtime(`runtime/<prefix>_<에이전트>-*`)과 그 에이전트의 실행 역할에만 닿도록 배포 build의 권한을 좁힌다(예: 심사를 시작할 때 세션 정책으로 좁힌 자격 증명을 build에 넘긴다). 이 방법은 여기서 확인하지 않았다.

## 알려진 한계: 시험 호출

TestCall은 HTTP 상태만 본다. 보통 질문(`What is the spec of part P-100?`)에 200이 오고 예시 access key가 든 질문이 403이면 통과다. 답의 내용은 보지 않는다. 2026-11-22의 실행에서 `release_review`는 이 질문이 변경 설명이 아니어서 `ERROR: unexpected model answer: ...`를 200으로 돌려줬고, 심사는 통과했다. 그래서 이 단계가 보여 주는 것은 Runtime이 뜨고, 게이트웨이와 정책을 지나 답이 오고, 비밀값이 진입에서 막힌다는 것까지다. 에이전트가 제대로 일하는지는 보지 않는다.

## 승인된 에이전트의 새 버전

팀이 승인된 에이전트를 다시 제출하면 같은 심사가 같은 이름으로 돈다. 역할, Runtime, target, 정책은 돌고 있는 버전의 것을 그대로 쓰고 고친다. 일어나는 일은 이 순서다. "2026-11-22의 실행에서 본 것"은 승인된 `quality_agent`의 새 버전을 두 번 심사하며 본 것이다. 심사 동안에는 30초 간격으로 열 번씩, 모두 스무 번 봤다.

1. record가 `PENDING_APPROVAL`이 되고 심사가 시작한다. 2026-11-22의 실행에서 본 것이다. 심사 동안 `GetRegistryRecord`는 스무 번 모두 새 신청서(새 `code_version`)를 돌려줬다. 그래서 Read는 방금 제출된 것을 심사한다. 개발팀 역할의 카탈로그 검색도 스무 번 모두 그 에이전트를 찾았다. 검색의 색인이 늦은 것인지 승인된 판이 검색되는 것인지는 알아보지 않았다.
2. Read: 같은 record의 심사가 먼저 시작해 아직 돌고 있으면, 뒤에 시작한 심사가 여기서 멈추고 알림으로 빠진다(`a review of this record is already running: <실행 이름>`). 먼저 시작한 심사는 그대로 돈다. 두 심사가 같은 역할, Runtime, 정책을 만들고 지우기 때문이다. 서비스 모델의 `ListExecutions` 설명은 실행 목록이 바로 맞지 않을 수 있다고 적는다(eventually consistent, 여기서는 확인하지 않았다). 그래서 목록에 자기 실행이 아직 없으면, 같은 record의 다른 실행을 모두 먼저 시작한 것으로 보고 멈춘다. 이 확인은 코드가 그렇게 하고 단위 시험이 확인한다. AWS에서는 심사 둘을 겹쳐 보지 않았다.
3. Grant: 실행 역할은 있는 것을 쓰고 그 inline 정책을 다시 쓴다(부를 수 있는 모델은 그때의 `MODEL_ID`다). 신청서에 없는 도구의 정책(`tool_<에이전트>_…`)을 지우고, 신청서의 도구마다 정책이 있게 한다. 지운 이름은 심사의 상태(`removedToolPolicies`)에 남는다. 도구 정책은 실행 역할을 가리키므로, 지운 때부터 돌고 있는 이전 버전도 그 도구를 부르지 못하고, 새로 건 때부터 새 도구를 부를 수 있다. 도구가 바뀌는 새 버전은 AWS에서 해 보지 않았다(단위 시험이 확인한다).
4. Deploy: Runtime `<prefix>_<에이전트>`를 고치고(`UpdateAgentRuntime`) 새 버전이 `READY`가 될 때까지 기다린다. 2026-11-22의 실행에서 본 것이다. Runtime의 버전이 하나 올라 `UPDATING`을 거쳐 241초와 221초 뒤에 `READY`가 되었다. 심사가 끝난 뒤 DEFAULT endpoint의 `liveVersion`은 새 버전이었고, 에이전트 게이트웨이를 지난 첫 호출이 새 코드에 닿았다. 그래서 Deploy가 끝나면 돌고 있는 코드는 새 버전으로 바뀌어 있다고 본다(Deploy가 끝난 순간의 `liveVersion`은 따로 보지 않았다). 그 뒤의 단계(Entry, TestCall, Approve)가 실패해도 허브는 되돌리지 않는다. 되돌리는 코드가 없다. Runtime이 `UPDATING`인 동안 사용자의 호출이 옛 버전에 닿는지, 새 버전에 닿는지, 오류가 나는지는 해 보지 않았다.
5. Entry, TestCall: 같은 Runtime을 가리키는 target과 정책은 있는 것을 쓰고, 시험 호출이 새 코드를 부른다. 이전 버전의 `entry_permit_<에이전트>`가 그대로 있으므로, 심사 동안에도 사용자는 그 에이전트를 부를 수 있다. Deploy가 끝난 뒤에는 그 호출이 시험 호출을 지나기 전의 새 코드에 닿는다(코드로 보면 그렇다. 심사 중의 사용자 호출은 해 보지 않았다).
6. Approve: record를 두 번 확인하고 `APPROVED`로 바꾼다. `entry_permit_<에이전트>`는 있는 것을 쓴다. Grant가 그것이 심사 전부터 있었다고 적었으므로(`entryPermitBefore`), Approve가 실패해도 지우지 않는다. 이전 버전의 것은 남는다.

2026-11-22의 실행에서 새 버전의 심사 둘은 모두 `SUCCEEDED`였고 308초와 296초 걸렸다(Deploy 266초와 244초). 역할, 정책, target이 이미 있을 때 Grant, Entry, Approve는 각각 2~3초였다. 끝나자 record는 `APPROVED`였다.

같은 날의 운영 확인(`make e2e-ops`)에서 지금의 심사 코드로 `quality_agent`의 새 버전을 두 번 심사했다(사고 버전 `v2-loop`, 그다음 에이전트가 멈춘 동안 고친 버전). 둘 다 `SUCCEEDED`였고 304초와 298초였다(Deploy 255초와 244초, 새 버전 `2`와 `3`이 `READY`가 되기까지 221초씩). Read는 같은 record의 앞선 심사를 찾으려고 실행 목록과 입력을 읽었고 거부된 것이 없었다. Grant가 적은 `entryPermitBefore`는 둘 다 `true`였고 Approve까지 닿았다. 도구가 바뀌지 않았으므로 지운 도구 정책(`removedToolPolicies`)은 없었다. 사고 버전의 심사 중에 개발팀 역할로 검색하자 그 에이전트가 나왔다. 멈춘 동안의 심사에서 시험 호출의 보통 질문은 200이었다(멈춤 정책의 예외).

새 버전이 어느 단계에서 떨어지면 알림이 가고, 허브는 아무것도 되돌리지 않는다. Grant가 새로 건 도구 정책은 남고 지운 정책은 되살아나지 않는다. Deploy가 끝났으면 떨어진 버전의 코드가 이전 버전의 `entry_permit_<에이전트>`로 사용자의 호출을 받는다. 반려하면 record만 `REJECTED`가 되고 에이전트는 그 상태로 돈다. 플랫폼팀은 `stop.sh <에이전트>`로 사용자를 막고, 팀이 고친 버전을 다시 제출한다. 단계마다 남는 것과 할 일은 아래 "심사가 실패했을 때"에 있다. 새 버전이 떨어지는 심사는 AWS에서 해 보지 않았다.

## 심사가 실패했을 때

알림의 제목은 `Hosting review failed at <단계>`이고, 내용(심사의 상태)에 실패한 단계(`failedStep`)와 오류(`error`)가 있다. record는 `PENDING_APPROVAL`에 남고, 앞의 단계가 만든 것과 바꾼 것도 남는다. 허브는 되돌리지 않는다. 무엇이 남는지는 그 에이전트에 승인된 버전이 돌고 있었느냐에 달렸다. 그것은 그 에이전트의 `entry_permit_<에이전트>`가 있는지로 안다(반려도 이것으로 정한다). Grant 뒤의 단계에서 떨어졌으면 알림의 내용에 Grant가 적은 `entryPermitBefore`가 있다(`true`면 이 심사 전부터 있었다). 이 절은 코드가 하는 일이다. AWS에서 본 것은 그렇다고 적었다.

| 떨어진 단계 | 처음 올리는 에이전트 | 승인된 에이전트의 새 버전 |
|---|---|---|
| Read, Scan | 만든 것이 없다. | 바뀐 것이 없다. 승인된 버전이 그대로 돈다. |
| Grant | 실행 역할과, Grant가 멈춘 데까지의 도구 정책. 사용자는 들어오지 못한다(`entry_permit_`이 없다). | 이전 버전의 코드가 돈다. 실행 역할의 inline 정책은 다시 쓰였고(모델은 지금의 `MODEL_ID`), 신청서에서 빠진 도구의 정책은 지워졌고, 새로 적은 도구의 정책은 Grant가 멈춘 데까지 걸렸다. 이것들은 돌고 있는 버전에 그대로 닿는다. |
| Deploy | 위의 것과 코드 묶음, Deploy가 간 데까지의 Runtime과 SSM의 `runtime_arn`. | 실행 역할과 도구 정책은 Grant가 바꾼 대로다. 무엇이 도는지는 Runtime이 어디까지 고쳐졌느냐에 달렸다(해 보지 않았다). |
| Entry, TestCall, Approve | 위의 것과 target, Entry가 건 `review_permit_`과 `guard_secret_`, Approve에서 떨어졌으면 그 앞에 건 전사 정책. 사용자는 들어오지 못한다(아래 "Approve가 건 `entry_permit_`이 남을 때"는 빼고). | 떨어진 버전의 코드가 Grant가 맞춘 도구 정책으로 돌고, 이전 버전의 `entry_permit_`으로 사용자의 호출을 받는다. |
| 그다음 `reject.sh`를 돌리면 | record가 `REJECTED`가 되고 위의 것을 모두 지운다(아래 "반려"). 팀은 사유를 읽고 고친 버전을 다시 제출한다. | record만 `REJECTED`가 되고 아무것도 지우지 않는다. 에이전트는 위의 상태로 계속 돈다. |

`MODEL_ID`가 그 에이전트의 지금 버전을 올린 뒤에 바뀌었다면, 새 버전이 Grant가 역할을 다시 쓴 뒤부터 Deploy가 Runtime을 고치기 전까지에서 떨어진 경우 돌고 있는 버전은 옛 모델을 부르는데 실행 역할은 새 모델만 허락한다. 정책으로 보면 그 버전의 모델 호출은 모두 거부된다. 새 버전의 심사가 이 사이를 지나는 동안에도 같다.

### 승인된 에이전트의 새 버전이 떨어졌을 때 할 일

Read나 Scan에서 떨어졌으면 바뀐 것이 없으므로, 팀이 고친 버전을 다시 제출하면 된다. Grant 뒤에서 떨어졌으면 돌고 있는 에이전트는 승인되지 않은 도구 정책이나 코드로 사용자의 호출을 받을 수 있다. 그때는 이 순서로 한다.

1. `platform_team/agent_stop/stop.sh <에이전트>`로 사용자를 막는다. 진입을 거부하는 `stop_agent_<에이전트>`를 걸고 그 Runtime의 최근 세션을 끝낸다. 심사의 시험 호출은 막지 않는다([에이전트 멈추기와 재개](../agent_stop/README.md)).
2. 팀에게 알릴 사유가 있으면 `reject.sh <에이전트> "<사유>"`를 돌린다. record가 `REJECTED`가 될 뿐 아무것도 지우지 않는다.
3. 팀이 고친 버전을 다시 제출한다(`publish.sh`). 올릴 때마다 코드의 version이 바뀌므로 record가 바뀌고 새 심사가 돈다. 그 심사의 Grant가 도구 정책을 새 신청서에 맞추고, Deploy가 Runtime을 고친다.
4. 그 심사가 승인되면 `platform_team/agent_stop/resume.sh <에이전트>`로 다시 연다. 심사는 멈춤 정책을 지우지 않는다.

2026-11-22의 운영 확인(`make e2e-ops`)에서 1, 3, 4를 이 순서로 돌렸다. 멈춘 동안 고친 버전의 심사가 `SUCCEEDED`였고, 승인된 뒤에도 사용자의 호출은 403이었고, `resume.sh` 뒤 첫 호출부터 200이었다. 그때 멈춘 것은 심사를 지난 버전이었다. 새 버전이 Grant 뒤에서 떨어지는 경우는 AWS에서 해 보지 않았다.

### 제출물의 잘못이 아닌 알림

- Read의 `a review of this record is already running: <실행 이름>`: 같은 record의 앞선 심사가 아직 돌고 있어서, 이 심사는 아무것도 만들거나 바꾸지 않고 멈췄다. 팀이 앞선 심사가 도는 동안 다시 제출했다면 record가 바뀌었으므로, 앞선 심사도 보통 Approve의 record 확인에서 떨어진다(`the record changed after the review started`). 그러면 두 심사가 멈춘 뒤 팀이 한 번 더 제출한다. 같은 이벤트로 심사가 두 번 시작했다면 앞선 심사는 그대로 돌고, 이 알림에는 할 일이 없다. 두 경우 모두 AWS에서 해 보지 않았다.
- Approve의 `policy <정책> is <모드>, but /<prefix>/policies/<전사 정책> is <모드>: the approval does not switch modes; rollout.sh … does`: 심사 중에 rollout이 이 에이전트에 전사 정책을 다른 모드로 걸었다(위의 일곱 단계의 Approve). Approve는 `entry_permit_<에이전트>`를 걸기 전에 멈췄다. 플랫폼팀이 알림이 말하는 `rollout.sh`로 모드를 맞추고, 팀이 다시 제출한다. 떨어진 심사는 다시 돌지 않는다. SSM에 rollout이 적지 않는 값이 있어 떨어졌을 때(`… not written by rollout`)도 그 값을 고친 뒤 다시 제출한다.
- Approve가 건 `entry_permit_<에이전트>`가 남을 때: Approve는 그 정책을 건 뒤에 실패하면 이번 심사에서 건 것을 지운다. 남는 것은 지우기도 실패했을 때(알림의 오류에 `taking back entry_permit_<에이전트>, which this review made, failed too`가 있다)와, 정책을 만든 뒤 단계가 끝나기 전에 Lambda가 끊겨(제한 시간, 메모리 부족 같은 중단) 지우는 코드가 돌지 않았을 때다. state machine은 Lambda 서비스의 오류 넷(`Lambda.ServiceException`, `Lambda.AWSLambdaException`, `Lambda.SdkClientException`, `Lambda.TooManyRequestsException`)에만 Approve를 다시 부른다(`Retry`). 다시 부른 Approve가 정책을 거는 데까지 가서 실패하면 앞의 시도가 건 것도 이번 심사의 것으로 알고 지우지만(끝까지 가면 승인한다), 그 앞(첫 record 확인, 전사 정책)에서 떨어지면 지우지 않는다. 제한 시간이나 메모리 부족이 이 넷으로 오는지는 확인하지 않았다. 정책이 남으면 승인된 적이 없는 에이전트에 사용자가 들어올 수 있다. `stop.sh <에이전트>`가 사용자를 막는다(Entry까지 돌았으므로 진입 target과 Runtime ARN이 있다). 반려는 그 정책을 보고 승인된 버전이 도는 것처럼 다루어 record만 `REJECTED`로 바꾸고 아무것도 지우지 않는다(record가 `DRAFT`면 거부한다). 에이전트 하나의 것을 지우는 명령은 없고 `make destroy`가 지운다. 팀이 다시 제출하면 그 심사는 이 정책을 심사 전부터 있던 것으로 본다(`entryPermitBefore`가 `true`). 이 경우들은 코드로 본 것이고 AWS에서는 해 보지 않았다.

## 반려

심사가 실패하면 state machine은 실패한 단계에서 멈추고 알림을 보낸다. record는 `PENDING_APPROVAL`에 남고, 앞 단계가 만든 것도 남는다. Grant의 실행 역할과 도구 정책, Deploy의 코드 묶음과 Runtime, Entry의 target과 정책이다. 플랫폼팀은 알림을 읽고 사유를 적어 반려한다. 반려는 record를 `REJECTED`로 바꾸고 남은 것을 지운다. 승인된 에이전트의 새 버전이면 record만 바꾼다(아래, 그리고 위의 "심사가 실패했을 때").

```
platform_team/hosting_review/reject.sh <에이전트> "<사유>"
platform_team/hosting_review/reject.sh quality_agent "jinja2 2.11.2 has published advisories"
```

어느 폴더에서 불러도 된다. 허브의 접두어와 리전은 `make`와 같은 규칙으로 리포의 `.env`에서 읽는다([README의 `.env`](../../README.md#env)). 첫 줄에 어느 허브인지(접두어, 리전) 찍고, 지운 것을 한 줄에 하나씩 찍는다. 실패하면 무엇이 실패했는지 한 줄로 찍고 0이 아닌 값으로 끝난다. 플랫폼팀의 자격 증명으로 돈다.

- 사유는 꼭 적는다(255자까지). 팀은 record에서 사유를 읽고, 고친 것을 다시 제출한다. 다시 제출하면 심사가 처음부터 돈다.
- 먼저 그 에이전트의 `entry_permit_<에이전트>`가 있는지 본다. 이 정책은 Approve만 만든다. Approve는 정책을 건 뒤에 실패하면 이번 심사에서 건 것을 지우고, 지우기가 실패하거나 Lambda가 그 사이에 끊길 때만 남긴다(위의 "심사가 실패했을 때"). 그래서 있으면 보통 이전 버전이 승인돼 돌고 있다. 반려는 정책만 볼 뿐 record가 승인된 적이 있는지는 모른다. 새 버전도 같은 이름의 역할, Runtime, target, 정책을 쓰므로, 이때는 record만 `REJECTED`로 바꾸고(이미 `REJECTED`면 상태와 사유를 그대로 둔다) 아무것도 지우지 않는다. 지운 것 대신 `entry_permit_<에이전트> is there: an approved version is running, or an approval that stopped left it; nothing was removed`를 찍는다(위의 "승인된 에이전트의 새 버전").
- 없으면 record의 상태에 따라 다르게 한다. `PENDING_APPROVAL`이면 `REJECTED`로 바꾸고 지운다. Registry가 반려를 받는 것은 승인 요청 상태의 record뿐이다. 이미 `REJECTED`면 상태와 사유는 그대로 두고 지우는 일만 다시 한다. 앞의 실행이 중간에 멈췄을 때 쓴다. `DRAFT`면 상태를 그대로 두고 지운다. 심사 중에 팀이 record를 고쳐(고친 record는 `DRAFT`가 된다) Approve가 멈춘 경우다. 사유는 record에 남지 않고, 상태 다음 줄에 `the record is a draft (the team changed it) and keeps its status`를 찍는다.
- `APPROVED`면 거부한다(`approved agents are stopped, not rejected`). 승인된 에이전트는 반려하지 않고 정지한다. `DRAFT`인데 `entry_permit_<에이전트>`가 있으면 거부한다. Registry는 `DRAFT`를 반려로 받지 않고, 반려는 그 정책이 승인된 버전의 것인지 알지 못하므로 지우지도 않는다. 그 밖의 상태이거나 record가 없어도 거부한다. 거부하면 아무것도 바꾸지 않는다.

### 지우는 것과 순서

| 순서 | 무엇 | 만든 단계 | 이름 | 지우는 방법 |
|---|---|---|---|---|
| 1 | 정책 | Approve, Entry, Grant | `entry_permit_<에이전트>`, `review_permit_<에이전트>`, 그 에이전트의 `tool_<에이전트>_<Target>_<도구>` 모두, `guard_secret_<에이전트>`, `guard_prompt_<에이전트>`, `stop_agent_<에이전트>` (이 순서). `guard_prompt_`와 `stop_agent_`는 없으면 건너뛴다. 도구 정책은 이름의 모양으로 찾으므로, 그 사이에 카탈로그에서 빠진 도구의 정책도 지운다 | `DeletePolicy`. 사라질 때까지 기다린다. |
| 2 | 에이전트 게이트웨이의 target | Entry | 에이전트 이름의 CamelCase(예: `QualityAgent`) | `DeleteGatewayTarget`. 사라질 때까지 기다린다. |
| 3 | harness | `make preload`(`CreateHarness`, harness 에이전트만) | `<prefix>_<에이전트>` | `DeleteHarness`. 사라질 때까지 기다린다(10분까지). 이미 `DELETING`이면 다시 지우지 않고 기다린다. `DELETE_FAILED`면 이름과 이유를 말하고 멈춘다. AgentCore가 harness를 돌리려고 만든 Runtime(`harness_<prefix>_<에이전트>`)과 그 workload identity는 2026-11-22의 실행에서 harness와 함께 사라졌다. |
| 4 | Runtime | Deploy(`CreateAgentRuntime`) | `<prefix>_<에이전트>` | `DeleteAgentRuntime`. 사라질 때까지 기다린다(10분까지). 이미 `DELETING`이면 다시 지우지 않고 기다린다. `DELETE_FAILED`면 Runtime 이름과 이유(`failureReason`)를 말하고 멈춘다. |
| 5 | Runtime의 로그 그룹 | Runtime 자신 | `/aws/bedrock-agentcore/runtimes/<Runtime 이름>-<ID 10자>-<endpoint>`. harness 에이전트는 harness가 돌던 Runtime의 것(`.../harness_<prefix>_<에이전트>-<ID 10자>-<endpoint>`) | `DeleteLogGroup` |
| 6 | 코드 묶음 | Deploy | 제출함의 `packages/<에이전트>/` 아래 | 모든 version과 삭제 표시를 지운다(`DeleteObject`에 `VersionId`). 제출함은 version을 남기기 때문이다. SSM에 플랫폼 값이 없으면 bucket 이름을 모르므로 지우지 않고, `terraform destroy`가 bucket을 비운다. |
| 7 | 실행 역할 | Grant(harness 에이전트는 `make preload`) | `<prefix>-agent-<에이전트>-role` | inline 정책을 먼저 지우고(`DeleteRolePolicy`) 역할을 지운다(`DeleteRole`). 권한 경계는 역할에 달려 있을 뿐이라 그대로 둔다. |
| 8 | SSM 값 | Deploy(harness 에이전트는 `make preload`의 `harness_arn`) | `/<prefix>/agents/<에이전트>/` 아래 | `DeleteParameter` |

순서에는 이유가 있다. 정책은 들여보내는 정책을 먼저 지우고 막는 정책(`guard_secret_`, `guard_prompt_`, `stop_agent_`)을 뒤에 지운다. 들여보내는 `entry_permit_<에이전트>`가 먼저 사라지므로 멈춘 에이전트가 정리 도중에 열리지 않는다. 이 순서는 코드와 시험이 정한 것이고, 실제 AWS에서는 여기서 확인하지 않았다. target은 Runtime을 가리키므로 Runtime보다 먼저 지운다. harness는 Runtime의 자리에서, Runtime보다 먼저 지운다. 로그 그룹은 Runtime이 사라진 뒤에 지워야 다시 생기지 않는다. 코드 묶음은 Runtime의 코드 위치이고, 실행 역할은 Runtime이 쓰므로 둘 다 Runtime 다음에 지운다. 역할과 SSM 값은 `make destroy`가 에이전트를 찾는 곳이라 맨 뒤에 둔다. 그래서 중간에 멈춰도 다시 돌리면 그 에이전트를 다시 찾는다.

이름은 모두 그 에이전트 하나의 것으로만 만든다. `Settings`와 `company_policy/policy_names.py`의 이름 함수로 만들고, 접두어로 넓게 찾아 지우지 않는다. 두 에이전트나 두 종류가 같은 이름을 만드는 일은 없다(위의 "정책 이름"). 그래서 `quality`를 반려해도 `quality_agent`의 `tool_quality_agent_...`, target `QualityAgent`, Runtime `hub_quality_agent`, 로그 그룹, 코드 묶음 `packages/quality_agent/`, 역할, SSM 값은 그대로다.

역할, Runtime, harness는 이름만으로는 허브의 것인지 알 수 없다. 그래서 지우기 전에 읽어서 확인한다(`check_agent`). 역할은 허브의 권한 경계 `<prefix>-agent-boundary`를 달고 있어야 한다. Grant는 이 경계 없이는 역할을 만들 수 없다. 또 managed 정책이나 instance profile이 없어야 한다. 허브는 둘 다 붙이지 않는다. Runtime은 Runtime 목록(모든 페이지)에서 이름 `<prefix>_<에이전트>`로 찾고, `GetAgentRuntime`으로 읽은 실행 역할(`roleArn`)이 그 에이전트의 역할 `<prefix>-agent-<에이전트>-role`이고 Runtime과 같은 계정의 것이어야 한다. 배포 역할은 어느 에이전트의 실행 역할이든 넘길 수 있기 때문이다. harness도 같다. harness 목록(모든 페이지)에서 이름 `<prefix>_<에이전트>`로 찾고, `GetHarness`로 읽은 실행 역할(`executionRoleArn`)이 그 에이전트의 역할이고 harness와 같은 계정의 것이어야 한다. 하나라도 맞지 않으면 그 에이전트의 것은 아무것도 지우지 않고, 무엇이 맞지 않는지 말하고 멈춘다. `reject`는 record의 상태를 바꾸기 전에 확인하므로, 이때 record도 그대로다. 확인은 읽기만 한다.

없는 것은 이미 지워진 것으로 본다. 그래서 두 번 돌려도 되고, 두 번째에는 지우는 것이 없다. 그 밖의 오류(권한이 없을 때 같은)가 나면 어느 단계에서 멈췄는지와 그 전에 지운 것을 말하고 멈춘다. 뒤의 단계는 돌지 않는다.

### 남기는 것

- 제출함의 zip. 무엇이 제출됐는지의 기록이다. bucket은 `terraform destroy`가 지운다.
- 카탈로그 record. `reject`는 record를 지우지 않는다. `REJECTED`와 사유가 남아 팀이 읽고 다시 제출한다. record를 지우는 것은 `make destroy`뿐이다(아래).

### `make destroy`

`make destroy`는 확인을 받은 뒤, 먼저 전사 정책의 모드(SSM `/<prefix>/policies/` 아래의 값)를 지운다(`company_policy/README.md`의 "`make destroy`"). 그다음 `terraform destroy` 앞에서 같은 정리를 모든 에이전트에 한다(`python -m platform_team.hosting_review.agent_cleanup`). 승인된 에이전트도 지우고, 에이전트마다 카탈로그 record까지 지운다. 에이전트는 세 곳에서 찾는다. 카탈로그의 AGENT record, SSM `/<prefix>/agents/` 아래의 값, `<prefix>-agent-<에이전트>-role` 이름의 역할이다. 그래서 카탈로그가 이미 없어도 찾는다. 역할은 허브의 권한 경계를 단 것만 에이전트로 본다. 이름은 맞지만 경계가 다르거나 없는 역할은 허브의 것이 아니므로 `skipped <역할>: not made by this hub`를 찍고 건너뛴다. 이 정리가 실패하면 `terraform destroy`를 돌리지 않는다. 에이전트 역할이 남아 있으면 Terraform이 권한 경계 정책을 지우지 못하고, record가 남아 있으면 Registry를 지우지 못하기 때문이다. 정리가 끝나면 공유 도구 record(seed)를 지운다. 그다음 `python -m platform_team.hosting_review.agent_cleanup --records`가 Registry에 남은 record를 종류와 이름에 상관없이 모두 지우고, 지운 record를 하나씩 찍는다(`removed record <이름> (<종류>, <상태>)`). AGENT가 아닌 record나 이름 규칙에 맞지 않는 record는 위의 정리가 에이전트로 찾지 못하는데, 남아 있으면 `terraform destroy`가 Registry에서 실패하기 때문이다. Registry는 허브의 것이고 바로 다음에 지워진다. 이 단계는 `make destroy`에만 있다. `reject`와 `remove_agent`는 record를 지우지 않는다. 그다음 `terraform destroy`를 돌린다.

### 한계

- 심사가 돌고 있는 동안에는 반려할 수 없다. 아직 도는 단계가 지운 것을 다시 만들기 때문이다. `reject`는 그 record의 심사가 `RUNNING`이면 아무것도 바꾸지 않고 거부한다(`a review of record <에이전트> is still running (<실행 이름>): reject after it stops`). 알림이나 Step Functions 콘솔에서 실행이 `FAILED`로 멈춘 것을 확인한 뒤 반려한다.
- 승인된 에이전트의 새 버전이 떨어지면 허브는 되돌리지 않는다. 돌고 있는 에이전트는 떨어진 버전이 Grant에서 받은 도구 정책을 갖고(빠진 도구의 정책은 되살아나지 않는다), Deploy가 끝났으면 그 버전의 코드로 돈다. 반려하면 record는 `REJECTED`인데 에이전트는 그 상태로 돈다. 돌아오는 길은 `stop.sh <에이전트>`로 사용자를 막고 팀이 고친 버전을 다시 제출하는 것이다(위의 "심사가 실패했을 때"). 새 버전이 심사에서 떨어지는 경우는 AWS에서 해 보지 않았다.
- 이 심사가 건 `entry_permit_<에이전트>`는 Approve가 지우다 실패하거나, 단계가 끝나기 전에 Lambda가 끊기고 그것을 지우는 Approve가 다시 돌지 않았을 때 남는다. 그러면 승인된 적이 없는 에이전트에도 사용자가 들어올 수 있다. `stop.sh <에이전트>`가 사용자를 막는다. 반려는 아무것도 지우지 않고, 에이전트 하나의 것을 지우는 명령은 없어서 `make destroy`가 지운다(위의 "심사가 실패했을 때"). 코드로 본 것이고 AWS에서는 해 보지 않았다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/main.tf` | 제출함(TLS만 받는 bucket 정책)과 코드 묶음, Lambda 다섯, CodeBuild 둘, state machine, 시작하는 rule, 로그 그룹(모두 Terraform이 만들고 `terraform destroy`가 지운다). 새 rule은 첫 이벤트를 놓치므로 90초를 기다린다(`time_sleep.rule_settles`). |
| `terraform/iam.tf` | 단계마다의 역할과 정책 문서(`read`, `scan`, `grant`, `deploy`, `entry`, `testcall`, `approve`), 에이전트 실행 역할의 권한 경계(`agent_boundary`), state machine과 rule의 역할, 제출함의 bucket 정책(`inbox`), 개발팀 역할에 붙이는 업로드 권한. |
| `terraform/review_machine.asl.json.tftpl` | state machine의 정의. Read에는 Registry의 이벤트와 이 실행의 ARN과 state machine의 ARN을 넘긴다(`$$.Execution.Id`, `$$.StateMachine.Id`). Read 뒤의 Choice `Reviewable`은 건너뛸 record(`skip`)를 `Skipped`(Succeed)로 보내고, 나머지는 Scan으로 보낸다. 모든 단계의 실패는 그 단계의 이름을 변수 `failedStep`에 적고 `Notify`(SNS)로 가서 `Failed`로 끝난다. `Notify`는 실패하면 세 번까지 다시 해 본다(`Retry`). |
| `terraform/variables.tf`, `terraform/outputs.tf` | 다른 모듈에서 받는 값(게이트웨이, policy engine, 카탈로그, 알림 주제, 개발팀 역할)과 내보내는 값(`bucket`, `machine_arn`. 시작점이 SSM `/<prefix>/platform/`에 적는다). |
| `review_steps.py` | Lambda 단계 다섯(Read, Grant, Entry, TestCall, Approve)의 코드. Read가 건너뛸 record를 고르는 것(`skip_reason`), 에이전트 실행 역할의 정책(`_execution_role`)과 그 역할을 만드는 함수(`ensure_agent_role`, Grant와 `make preload`가 쓴다)도 여기 있다. |
| `lambda_handler.py` | Lambda의 진입점. 환경 변수 `ACTION`이 단계를 고르고, 제한 시간 60초 전을 단계의 마감으로 넘긴다. |
| `buildspec_scan.yml`, `submission_check.py` | 검사 단계. 제출물의 압축을 안전하게 풀고 모양과 `requirements.txt`를 확인하고, 규칙에 맞는 줄을 플랫폼의 파일에 다시 써서(`requirements_from`, 배포 build도 쓴다) 그 파일에 `pip-audit`를 돌린다. |
| `buildspec_deploy.yml`, `deploy_build.py` | 배포 단계. 제출된 코드와 의존성을 묶어 Runtime을 만들거나 고친다(위의 "배포 build가 하는 일"). |
| `reject.sh`, `reject_agent.py` | 반려. record를 `REJECTED`로 바꾸고 심사가 만든 것을 지운다. 승인된 버전이 돌고 있으면 record만 바꾼다(위의 "반려"). Read도 여기의 `running_reviews`로 같은 record의 앞선 심사를 찾는다. |
| `preload_agents.py` | 처음부터 올라와 있는 에이전트 둘(`make preload`). harness 에이전트 `spec_assistant`는 역할, 도구 정책, harness, 승인된 record를 만들고(`host_harness`), 코드가 있는 `docs_adk`는 다른 팀의 에이전트처럼 제출하고 심사가 끝나기를 기다린다. harness에 질문 하나를 보내는 `ask_harness`도 여기 있다. 플랫폼팀의 자격 증명으로 돈다. |
| `agent_cleanup.py` | 심사가 에이전트 하나에 만든 것을 지운다(`remove_agent`). `make destroy`는 모든 에이전트에 부르고(`clean_agents`), 마지막에 Registry에 남은 record를 모두 지운다(`--records`, `remove_records`). |
