# 개발팀의 권한

개발팀이 심사를 받기 전부터 할 수 있는 일을 정한다. 개발팀 역할 `<prefix>-dev-role`을 맡으면 세 가지를 할 수 있다. 도구 게이트웨이로 공유 읽기 도구(`SHARED_READ`, 지금은 `Parts___get_part_spec`)를 부르고, 카탈로그를 검색하고, record를 만들어 승인을 요청한다. 이 역할을 맡을 수 있는 주체는 `dev_principals`가 정한다(기본값은 이 계정).

## 개념도에서의 위치

그림의 "개발팀"이 쓰는 권한이다. 따로 그린 상자는 없다. ①과 ②에서 카탈로그를 쓰는 권한이 여기에 있다. 에이전트를 만드는 동안 공유 도구를 부르게 하는 Cedar permit `shared_tool_read`는 전사 정책의 engine에 들어간다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | 개발팀 역할(도구 게이트웨이의 `InvokeGateway`, Registry의 조회와 record 만들기와 승인 요청)과 Cedar 정책 `shared_tool_read`(문장은 `company_policy/policy_templates/shared-tool-read.cedar`). 내보내는 값은 `dev_role_arn`, `dev_role_name`. 제출함에 올리는 권한은 호스팅 심사(`hosting_review`)가 이 역할에 붙인다. |
