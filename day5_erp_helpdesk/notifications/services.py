"""
notifications 앱 - 알림(이메일) 발송 함수

※ 아직 실제 메일은 보내지 않습니다. 다음 단계에서 아래 함수 안을 채우면
   문의 등록 등 업무 처리 코드는 고치지 않아도 메일이 연결됩니다.
"""

import logging

logger = logging.getLogger(__name__)


def notify_inquiry_created(inquiry):
    """
    문의가 접수되었을 때 호출됨 (inquiries.services.create_inquiry에서 호출)

    TODO (메일 발송 단계에서 구현):
      - 받는 사람: 요청자(접수 확인), ERP 담당자들(신규 문의 알림)
      - EmailLog에 PENDING으로 기록 → 발송 → SENT/FAILED로 갱신
      - 메일 계정 정보는 .env에서 읽기
    """
    logger.info('[메일 발송 예정] 문의 접수: %s %s', inquiry.inquiry_no, inquiry.title)


def notify_status_changed(inquiry, old_status, new_status):
    """
    문의 상태가 바뀌었을 때 (inquiries.services.change_status에서 호출)
    TODO: 요청자에게 상태 변경 알림. 특히 답변 완료·처리 완료·보류·반려는 꼭 알림
    """
    logger.info('[메일 발송 예정] 상태 변경: %s %s → %s', inquiry.inquiry_no, old_status, new_status)


def notify_assigned(inquiry, job):
    """
    담당 직무가 지정되었을 때 (inquiries.services.assign에서 호출)
    TODO: 해당 직무(User.job)를 가진 담당자 전원에게 배정 알림
    """
    logger.info('[메일 발송 예정] 담당 직무 지정: %s → %s', inquiry.inquiry_no, job)


def notify_comment_added(comment):
    """
    답변·코멘트가 등록되었을 때 (inquiries.services.add_comment에서 호출)
    TODO: 답변이면 요청자에게, 사용자 코멘트면 담당자에게 알림 (내부 메모는 알림 없음)
    """
    logger.info('[메일 발송 예정] %s 등록: %s', comment.get_type_display(), comment.inquiry.inquiry_no)
