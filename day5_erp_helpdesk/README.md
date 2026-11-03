# ERP 문의 관리 시스템 (ERP Helpdesk)

사내 직원이 ERP 문의·개선 요청을 등록하고, ERP 담당자가 접수 → 담당자 지정 → 답변 → 처리 완료까지 관리하는 웹 시스템입니다.

## 실행 방법

```bash
# 1. 가상환경 만들기 (처음 한 번)
python3 -m venv .venv

# 2. 가상환경 켜기
source .venv/bin/activate

# 3. 패키지 설치
pip install -r requirements.txt

# 4. 설정 파일 만들기 (처음 한 번) → .env를 열어 SECRET_KEY를 채움
cp .env.example .env

# 5. DB 테이블 만들기
python manage.py migrate

# 6. 샘플 데이터 만들기 (--reset 을 붙이면 문의·공지를 지우고 다시 생성)
python manage.py seed_data

# 7. 서버 실행
python manage.py runserver 8001
```

관리자 페이지: http://127.0.0.1:8001/admin/

## 샘플 계정

> ⚠️ 개발·테스트용 계정입니다. 운영 서버에서는 사용하지 마세요.
> 비밀번호는 모두 `.env`의 `SEED_PASSWORD` 값입니다. 기본값은 **`erp1234!`** 입니다.

| 역할 | 아이디 | 이름 | 부서 | Admin 접속 |
|---|---|---|---|---|
| 관리자 (ADMIN) | `admin` | 서지원 | 품질 | 가능 (최고 관리자) |
| ERP 담당자 (AGENT) | `agent1` | 한소영 | 회계 | 가능 |
| ERP 담당자 (AGENT) | `agent2` | 강태현 | 품질 | 가능 |
| ERP 담당자 (AGENT) | `agent3` | 윤하은 | 영업 | 가능 |
| 일반 사용자 (USER) | `user1` | 김민준 | EMC | 불가 |
| 일반 사용자 (USER) | `user2` | 이서연 | Safety | 불가 |
| 일반 사용자 (USER) | `user3` | 박지훈 | Medical | 불가 |
| 일반 사용자 (USER) | `user4` | 최수아 | 영업 | 불가 |
| 일반 사용자 (USER) | `user5` | 정도윤 | 무선 | 불가 |

※ 담당자 계정은 Admin에 들어갈 수는 있지만, 아직 메뉴 권한을 주지 않아 화면이 비어 보입니다. Admin 확인은 `admin` 계정으로 하세요.

## 샘플 데이터 구성

- 부서 7개: EMC, Safety, Medical, 영업, 무선, 품질, 회계
- 문의 분류 4개: 권한 요청, 오류 신고, 개선 요청, 기타 요청
- 문의 40건 (최근 90일)

  | 상태 | 접수 | 확인 중 | 처리 중 | 답변 완료 | 처리 완료 | 보류 | 반려 |
  |---|---|---|---|---|---|---|---|
  | 건수 | 6 | 5 | 8 | 7 | 9 | 3 | 2 |

- 문의별 답변·내부 메모·사용자 댓글과 처리 이력, 관련 문의 연결 3건
- 공지사항 6건 (상단 고정 2건)
