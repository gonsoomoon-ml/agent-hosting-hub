# 개발팀의 권한

개발팀이 심사를 받기 전부터 할 수 있는 일을 정한다. 개발팀 역할 `<prefix>-dev-role`을 맡으면 네 가지를 할 수 있다. 도구 게이트웨이로 공유 읽기 도구(`SHARED_READ`, 지금은 `Parts___get_part_spec`)를 부르고, 카탈로그를 검색하고, record를 만들어 승인을 요청하고, 허브의 값(SSM `/<prefix>/platform/` 아래의 게이트웨이와 카탈로그의 ID, 제출함의 이름)을 읽는다. `publish.sh`가 이 역할로 돌면서 제출함과 카탈로그를 여기서 찾기 때문이다. 이 권한은 실행해서 찾았다(`ssm:GetParametersByPath`가 없어 제출이 거부됐다). 이 역할을 맡을 수 있는 주체는 `dev_principals`가 정한다(기본값은 이 계정).

## 개념도에서의 위치

그림의 "개발팀"이 쓰는 권한이다. 따로 그린 상자는 없다. ①과 ②에서 카탈로그를 쓰는 권한이 여기에 있다. 에이전트를 만드는 동안 공유 도구를 부르게 하는 Cedar permit `shared_tool_read`는 전사 정책의 engine에 들어간다.

## 카탈로그 권한의 범위

개발팀 역할은 카탈로그에서 다섯 가지를 할 수 있다. 검색, record 읽기, record 만들기, record 고치기, 승인 요청이다. 에이전트를 올리는 흐름과 반려 뒤의 재신청이 이 역할로 돌아서 record를 고치는 권한이 필요하다. record의 ARN에는 무작위 ID가 들어가므로 IAM으로는 record를 만든 팀별로 권한을 나눌 수 없고, 이 권한은 Registry의 모든 record에 걸린다. 그래서 이 역할로 다른 팀의 record나 플랫폼팀의 공유 도구 record(`parts-tools`)도 고칠 수 있다. 승인된 record를 고치면 새 DRAFT가 되고, 다시 승인될 때까지 검색에 나오지 않는다. 운영 환경이라면 record에 주인 태그를 달고 IAM 조건으로 막거나, record를 고치는 일을 플랫폼 쪽의 게시 함수가 맡게 해서 이 틈을 닫는다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | 개발팀 역할(도구 게이트웨이의 `InvokeGateway`, 허브의 값 읽기(`ssm:GetParametersByPath`, `/<prefix>/platform`), Registry의 조회와 record 만들기와 승인 요청)과 Cedar 정책 `shared_tool_read`(문장은 `company_policy/policy_templates/shared-tool-read.cedar`). 내보내는 값은 `dev_role_arn`, `dev_role_name`. 제출함에 올리는 권한은 호스팅 심사(`hosting_review`)가 이 역할에 붙인다. |
