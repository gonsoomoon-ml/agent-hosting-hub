# 샘플 사내 도구

허브의 도구 게이트웨이 뒤에서 동작하는 샘플 도구 모음이다. 회사가 가진 자체 시스템(검사, 부품, 배포 검토)을 흉내 낸 것이고, 모든 데이터는 합성이다. 실제 회사, 제품, 사람, 계정 정보는 없다.

## 개념도에서의 위치

개념도의 "사내 도구" 상자다. ⑨ "허용된 호출만 전달" 단계에서 게이트웨이가 정책을 통과한 호출만 이 Lambda로 넘긴다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | Lambda `<prefix>-tools`, 그 역할 `<prefix>-tools-lambda-role`, 로그 그룹. 코드는 허브의 코드 묶음 `build/platform_team.zip`(`make package`가 만든다)이다. 내보내는 값은 `lambda_arn`. |
| `tool_handler.py` | Lambda 진입점. 도구 이름(`<Target>___<tool>`)을 읽어 알맞은 도구를 실행한다. 표준 라이브러리만 쓰고 상태를 저장하지 않는다. |
| `tool_data.py` | 합성 검사 건, 부품, 시험 결과. |
| `tool_schema.py` | 게이트웨이에 등록할 도구 스키마(`TARGETS`)와 승인된 공유 읽기 도구(`SHARED_READ`). |
