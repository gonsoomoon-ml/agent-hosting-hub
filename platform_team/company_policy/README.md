# 전사 정책

허브의 모든 정책이 들어가는 policy engine 하나(`<prefix>_pe`)를 만든다. 두 게이트웨이가 이 engine을 함께 쓰고 `ENFORCE`로 따른다. 정책은 Cedar로 쓴다. 개발팀의 공유 도구 permit(`dev_access`), 호스팅 심사가 주는 permit(도구, 요청), 플랫폼팀이 거는 전사 정책(가드레일, 차단)이 모두 이 engine에 있다.

## 개념도에서의 위치

⑫ "전사 정책 설정, 이상 에이전트 차단"이다. 플랫폼팀이 이 engine에 정책을 넣으면 두 게이트웨이가 바로 따른다. ④ "에이전트에 도구 권한 부여"와 ⑥ "요청 허용"의 permit도 여기에 들어간다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | policy engine `<prefix>_pe`. 내보내는 값은 `policy_engine_id`, `policy_engine_arn`. |
| `cedar_statements.py` | 템플릿에 값을 채워 Cedar 문장을 만든다(도구 permit, 사용자의 요청 permit `entry_permit`, 시험 호출만의 요청 permit `review_permit`, 가드레일 정책, 질문의 공격을 막는 `guard_prompt`, 에이전트를 멈추는 `stop_agent`). 값이 비었거나 따옴표, 역슬래시, 줄바꿈이 들어 있거나, 채우지 않은 자리(`<...>`)가 남으면 문장을 만들지 않고 오류를 낸다. |
| `policy_templates/` | Cedar 문장의 템플릿. `<account>` 같은 자리에 값을 채운다. Python과 Terraform이 같은 파일을 읽는다. |
| `policy_names.py` | 호스팅 심사가 에이전트마다 만드는 정책의 이름(`tool_...`, `review_permit_...`, `guard_secret_...`, `entry_permit_...`, 질문의 공격을 막는 `guard_prompt_...`, 에이전트를 멈추는 `stop_agent_...`)과 정책 이름의 한도(48자). 신청서 검사, 심사 단계, 반려가 모두 이 파일을 쓴다(`hosting_review/README.md`의 "정책 이름"). |
| `policy_engine.py` | 정책을 만들고(`ensure_policy`), 지우고(`drop_policy`), 목록을 읽는다(`list_policies`). 같은 이름의 정책이 있으면 그대로 두되, 적용 모드(`ACTIVE`, `LOG_ONLY`)가 다르면 `set_mode`로 맞춘다. |
