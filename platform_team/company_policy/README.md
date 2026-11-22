# 전사 정책

허브의 모든 정책이 들어가는 policy engine 하나(`<prefix>_pe`)를 만든다. 두 게이트웨이가 이 engine을 함께 쓰고 `ENFORCE`로 따른다. 정책은 Cedar로 쓴다. 개발팀의 공유 도구 permit(`dev_access`), 호스팅 심사가 주는 permit(도구, 요청), 플랫폼팀이 거는 전사 정책(가드레일, 차단)이 모두 이 engine에 있다.

## 개념도에서의 위치

⑫ "전사 정책 설정, 이상 에이전트 차단"이다. 플랫폼팀이 이 engine에 정책을 넣으면 두 게이트웨이가 바로 따른다. ④ "에이전트에 도구 권한 부여"와 ⑥ "요청 허용"의 permit도 여기에 들어간다.

## 전사 정책 켜고 끄기

전사 정책은 플랫폼팀이 허브에 올라온 모든 에이전트에 거는 정책이다. 에이전트마다 하나씩 건다. 지금 있는 전사 정책은 `guard_prompt` 하나다. 프롬프트 공격(`PROMPT_INJECTION`, 신뢰도 0.4 초과)인 질문을 에이전트 게이트웨이에서 거부하는 가드레일 정책이고, 에이전트마다 이름은 `guard_prompt_<에이전트>`다.

이 절의 동작은 코드와 단위 시험(`tests/test_policy_rollout.py`, `tests/test_review_steps.py`)이 정한 것이다. 명령과 Approve가 전사 정책을 거는 것은 아직 AWS에서 돌려 보지 않았다.

### 상태와 적용 모드

정책에는 값이 둘 있다. 상태(`status`: `CREATING`, `ACTIVE`, `UPDATING` 등)는 정책이 다 만들어졌는지를 말한다. 적용 모드(`enforcementMode`: `ACTIVE`, `LOG_ONLY`)는 정책의 결정이 요청에 반영되는지를 말한다. 두 값이 같은 낱말 `ACTIVE`를 쓰지만 뜻이 다르다. 상태가 `ACTIVE`인 정책은 다 만들어진 것이고, 적용 모드가 `ACTIVE`인 정책은 그 결정이 요청에 반영된다.

서비스 모델(botocore 1.44.9, `CreatePolicy`의 `enforcementMode`)은 기록 모드(`LOG_ONLY`)를 이렇게 설명한다. 이 모드로 돌려 정책이 애플리케이션에 주는 영향을 자료로 모으고, 자료가 충분하면 `ACTIVE`로 바꾼다. 그래서 전사 정책은 먼저 기록 모드(`log-only`)로 켜서 무엇에 맞는지 보고, 그다음 적용 모드(`active`)로 올린다. 기록 모드의 정책이 요청을 막지 않는다는 것은 이 허브에서 AWS로 확인하지 않았다. 모드를 바꿀 때 정책을 다시 만들지 않는다. 같은 정책의 적용 모드만 바꾸고(`UpdatePolicy`), 상태가 다시 `ACTIVE`가 될 때까지 기다린다. 모드를 바꾸다 실패해도 있던 정책은 지우지 않는다.

### 명령 넷

```
platform_team/company_policy/rollout.sh guard_prompt log-only   # 켠다: 모든 에이전트에 기록 모드로
platform_team/company_policy/rollout.sh guard_prompt active     # 올린다: 결정을 요청에 반영한다
platform_team/company_policy/rollout.sh guard_prompt off        # 끈다: 모든 에이전트에서 지운다
platform_team/company_policy/rollout.sh guard_prompt report     # 에이전트마다 지난 60분의 기록을 읽는다
```

어느 폴더에서 불러도 된다. 허브의 접두어와 리전은 `make`와 같은 규칙으로 리포의 `.env`에서 읽는다([README의 `.env`](../../README.md#env)). 첫 줄에 어느 허브인지(접두어, 리전) 찍는다. 플랫폼팀의 자격 증명으로 돈다. 모르는 정책이나 낱말이면 사용법을 찍고 아무것도 바꾸지 않는다.

- `log-only`, `active`: 모드를 SSM `/<prefix>/policies/<정책>`에 먼저 적고(`LOG_ONLY`, `ACTIVE`), 그다음 호스팅된 에이전트마다 정책을 그 모드로 만들거나 모드를 맞춘다. 에이전트마다 한 줄씩 `created`(새로 만들었다), `switched`(모드를 바꿨다), `unchanged`(이미 그 모드였다), `failed (<이유>)`를 찍는다. 한 에이전트가 실패해도 나머지 에이전트는 계속한다. 하나라도 실패하면 0이 아닌 값으로 끝난다. SSM의 모드는 적힌 채로 남으므로 같은 명령을 다시 돌리면 된다. 같은 명령을 두 번 돌리면 두 번째에는 모두 `unchanged`다.
- `off`: SSM의 값을 먼저 지우고, 그다음 이 정책을 가진 모든 에이전트에서 정책을 지운다. 진입 target이 없는 에이전트의 것도 이름으로 찾아 지운다. 다른 종류의 정책은 그대로다.
- `report`: 이 정책을 가진 에이전트마다 적용 모드와, 지난 60분 동안의 CloudWatch 메트릭 `LogOnlyMatches`와 `LogOnlyDecisionFlips`의 합(`Sum`)을 찍는다. 네임스페이스는 `AWS/Bedrock-AgentCore`이고, 차원은 `OperationName=AuthorizeAction`, `Policy=<정책 ID>`, `PolicyEngine=<engine ID>`, `TargetResource=<에이전트 게이트웨이 ID>`다. 이 메트릭 이름과 차원은 2026-11-22에 계정의 메트릭 목록에서 봤다. 정책의 차원 값은 정책의 이름이 아니라 ID였다. `report`는 AWS에서 돌려 보지 않았다. 그래서 여기 적은 것은 이 명령이 읽는 것이지, 읽어서 나온 값이 아니다.

호스팅된 에이전트는 SSM `/<prefix>/agents/<에이전트>/` 아래에 값이 있고, 에이전트 게이트웨이에 진입 target이 있는 에이전트다. 심사 중인 에이전트도 Entry 단계가 target을 만든 뒤라면 여기에 든다. harness 에이전트에는 진입 target이 없어서 전사 정책이 걸리지 않는다. 심사가 harness를 호스팅하지 않기 때문이다(`hosting_review/README.md`).

### 새로 승인되는 에이전트

호스팅 심사의 Approve 단계는 사용자를 들이는 `entry_permit_<에이전트>`를 걸기 전에, SSM `/<prefix>/policies/` 아래에 적힌 전사 정책을 그 모드 그대로 새 에이전트에 건다. 그래서 나중에 승인되는 에이전트도 다른 에이전트와 같은 정책을 같은 모드로 갖고 시작한다. 켜진 전사 정책이 없으면 Approve는 `entry_permit_<에이전트>`만 건다. 같은 이름의 정책이 이미 그 모드로 있으면 그대로 쓴다. 다른 모드로 있으면 Approve는 모드를 바꾸지 않고 실패한다. 모드는 rollout이 바꾼다(Approve의 역할에는 `UpdatePolicy`가 없다). SSM에 rollout이 적지 않는 값(모르는 정책이나 모드)이 있을 때도 Approve는 정책을 걸지 않고 실패한다. 두 경우 모두 승인 없이 알림으로 빠진다.

### 모드를 먼저 적는 이유

rollout은 모드를 SSM에 먼저 적고, 그다음에 호스팅된 에이전트를 찾는다. 순서가 반대라면 빠지는 에이전트가 생길 수 있다. 에이전트 목록을 읽은 뒤, SSM에 적기 전에 승인된 에이전트다. 그 에이전트는 목록에 없으니 rollout이 정책을 걸지 않고, 승인할 때 SSM에 모드가 아직 없었으니 Approve도 걸지 않는다.

모드를 먼저 적으면 빠지는 에이전트가 없다. 적기 전에 승인된 에이전트는 Entry 단계가 만든 진입 target이 이미 있으므로 목록에 들고, 적은 뒤에 승인되는 에이전트는 Approve가 새 모드를 읽는다. `off`도 같은 이유로 SSM 값을 먼저 지우고 정책을 나중에 지운다. 이 순서는 코드와 단위 시험이 정한 것이고, AWS에서 두 일을 동시에 일어나게 해 보지는 않았다.

### `make destroy`

`make destroy`는 에이전트를 정리하기 전에 SSM `/<prefix>/policies/` 아래의 값을 지운다(`python -m platform_team.company_policy.policy_rollout --forget`). 정책 자체는 그다음의 에이전트 정리가 에이전트마다 지운다. 이 값은 Terraform 밖에 있어서 `terraform destroy`가 지우지 않는다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | policy engine `<prefix>_pe`. 내보내는 값은 `policy_engine_id`, `policy_engine_arn`. |
| `cedar_statements.py` | 템플릿에 값을 채워 Cedar 문장을 만든다(도구 permit, 사용자의 요청 permit `entry_permit`, 시험 호출만의 요청 permit `review_permit`, 가드레일 정책, 질문의 공격을 막는 `guard_prompt`, 에이전트를 멈추는 `stop_agent`). 값이 비었거나 따옴표, 역슬래시, 줄바꿈이 들어 있거나, 채우지 않은 자리(`<...>`)가 남으면 문장을 만들지 않고 오류를 낸다. |
| `policy_templates/` | Cedar 문장의 템플릿. `<account>` 같은 자리에 값을 채운다. Python과 Terraform이 같은 파일을 읽는다. |
| `policy_names.py` | 호스팅 심사가 에이전트마다 만드는 정책의 이름(`tool_...`, `review_permit_...`, `guard_secret_...`, `entry_permit_...`, 질문의 공격을 막는 `guard_prompt_...`, 에이전트를 멈추는 `stop_agent_...`)과 정책 이름의 한도(48자). 신청서 검사, 심사 단계, 반려가 모두 이 파일을 쓴다(`hosting_review/README.md`의 "정책 이름"). |
| `policy_engine.py` | 정책을 만들고(`ensure_policy`), 지우고(`drop_policy`), 목록을 읽는다(`list_policies`). 같은 이름의 정책이 있으면 그대로 두되, 적용 모드(`ACTIVE`, `LOG_ONLY`)가 다르면 `set_mode`로 맞춘다. |
| `policy_rollout.py` | 전사 정책의 목록(`POLICIES`)과 낱말(`MODE_WORDS`), 켜고 모드를 맞추기(`rollout`), 끄기(`remove`), 켜져 있는 정책과 모드(`deployed`), 호스팅된 에이전트(`hosted_agents`), 새 에이전트에 걸기(`apply_to_agent`, 심사의 Approve가 부른다), 메트릭 읽기(`report`), SSM 값만 지우기(`forget`, `make destroy`가 부른다). |
| `rollout.sh` | 위의 명령 넷. 리포의 `.env`를 `make`와 같은 규칙으로 읽고 `policy_rollout`을 부른다. |
