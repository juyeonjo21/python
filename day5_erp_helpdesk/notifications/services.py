"""
notifications 앱 - 알림(이메일) 발송 함수

inquiries/services.py가 DB 저장이 끝난 뒤(transaction.on_commit) 아래 함수를 부릅니다.
  - 누구에게 보낼지 : policy.py
  - 실제 발송·기록  : email.py (실패해도 오류를 밖으로 던지지 않음)
"""

import logging

from accounts.models import Job
from inquiries.models import Comment, Inquiry

from . import policy
from .email import send_notification
from .models import EmailLog

logger = logging.getLogger(__name__)
E = EmailLog.EventType


def notify_inquiry_created(inquiry):
    """문의 등록 → 담당자들에게 '새 문의', 요청자에게 '접수 확인'"""
    try:
        staff, requester = policy.created_recipients(inquiry)
        send_notification(E.CREATED, inquiry, staff, 'inquiry_created_staff', {'situation': '새 문의'})
        send_notification(E.CREATED, inquiry, requester, 'inquiry_created_requester', {'situation': '접수 완료'})
    except Exception:
        logger.exception('문의 등록 알림 실패: %s', inquiry.inquiry_no)


def notify_status_changed(inquiry, old_status, new_status, actor=None):
    """상태 변경 → 요청자 (처리 완료·보류·반려일 때만, 보류·반려는 사유 포함)"""
    try:
        recipients = policy.status_changed_recipients(inquiry, new_status, actor)
        new_label = Inquiry.Status(new_status).label
        send_notification(E.STATUS_CHANGED, inquiry, recipients, 'inquiry_status_changed', {
            'situation': new_label,
            'old_label': Inquiry.Status(old_status).label,
            'new_label': new_label,
            'new_status': new_status,
            'reason': inquiry.resolution,
        })
    except Exception:
        logger.exception('상태 변경 알림 실패: %s', inquiry.inquiry_no)


def notify_assigned(inquiry, job, actor=None):
    """직무 지정 → 그 직무 담당자 전원 (지정한 본인 제외)"""
    try:
        recipients = policy.assigned_recipients(inquiry, job, actor)
        send_notification(E.ASSIGNED, inquiry, recipients, 'inquiry_assigned', {
            'situation': '직무 배정',
            'job_label': Job(job).label,
        })
    except Exception:
        logger.exception('직무 지정 알림 실패: %s', inquiry.inquiry_no)


def notify_comment_added(comment):
    """답변 → 요청자 / 사용자 코멘트 → 담당 직무(없으면 전체 담당자) / 내부 메모 → 없음"""
    try:
        recipients = policy.comment_recipients(comment)
        if comment.type == Comment.Type.ANSWER:
            send_notification(E.ANSWERED, comment.inquiry, recipients, 'inquiry_answered', {
                'situation': '답변 등록',
                'comment_body': comment.content,
                # 답변자 이름 대신 직무만 표시 (다른 사용자의 개인정보 최소화)
                'answered_by': f'ERP 담당자 ({comment.author.get_job_display()})' if comment.author.job else 'ERP 담당자',
            })
        elif comment.type == Comment.Type.USER:
            send_notification(E.COMMENTED, comment.inquiry, recipients, 'inquiry_commented', {
                'situation': '요청자 코멘트',
                'comment_body': comment.content,
            })
    except Exception:
        logger.exception('답변·코멘트 알림 실패: comment %s', comment.pk)
