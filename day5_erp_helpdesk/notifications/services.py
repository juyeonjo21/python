"""
notifications 앱 - 알림(웹 알림·이메일) 보내기

inquiries/services.py가 DB 저장이 끝난 뒤(transaction.on_commit) 아래 함수를 부릅니다.
처리 순서: ① 웹 알림(inapp.py) → ② 이메일(email.py)
  - 채널을 켤지·끌지, 누구에게 보낼지 : policy.py (CHANNELS 표)
  - 알림 문장                          : messages.py
  - 웹 알림이 실패해도 이메일은 보내고, 둘 다 실패해도 업무 처리는 그대로 성공
"""

import logging

from accounts.models import Job
from inquiries.models import Comment, Inquiry

from . import messages, policy
from .email import send_notification
from .inapp import create_notifications
from .models import EmailLog

logger = logging.getLogger(__name__)
E = EmailLog.EventType


def notify_inquiry_created(inquiry):
    """문의 등록 → 담당자 전원 웹 알림 (긴급이면 메일도) / 요청자 접수 확인(지금은 꺼짐)"""
    actor = inquiry.requester
    try:
        if policy.channel_on('CREATED_STAFF', 'web', inquiry=inquiry):
            create_notifications(E.CREATED, inquiry, policy.created_staff_recipients(inquiry, 'web'),
                                 actor, messages.created(inquiry))
        if policy.channel_on('CREATED_STAFF', 'email', inquiry=inquiry):
            send_notification(E.CREATED, inquiry, policy.created_staff_recipients(inquiry, 'email'),
                              'inquiry_created_staff', {'situation': '새 문의'})
        if policy.channel_on('CREATED_REQUESTER', 'email', inquiry=inquiry):
            send_notification(E.CREATED, inquiry, policy.created_requester_recipients(inquiry),
                              'inquiry_created_requester', {'situation': '접수 완료'})
    except Exception:
        logger.exception('문의 등록 알림 실패: %s', inquiry.inquiry_no)


def notify_status_changed(inquiry, old_status, new_status, actor=None):
    """상태 변경 → 요청자 웹 알림 (모든 상태) + 메일 (처리 완료·보류·반려만, 보류·반려는 사유 포함)"""
    try:
        recipients = policy.status_changed_recipients(inquiry, actor)
        context = {'inquiry': inquiry, 'new_status': new_status}
        if policy.channel_on('STATUS_CHANGED', 'web', **context):
            create_notifications(E.STATUS_CHANGED, inquiry, recipients, actor,
                                 messages.status_changed(inquiry, new_status, actor))
        if policy.channel_on('STATUS_CHANGED', 'email', **context):
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
    """직무 지정 → 그 직무 담당자 웹 알림 (지정한 본인 제외, 메일은 지금 꺼짐)"""
    try:
        recipients = policy.assigned_recipients(inquiry, job, actor)
        job_label = Job(job).label
        if policy.channel_on('ASSIGNED', 'web', inquiry=inquiry):
            create_notifications(E.ASSIGNED, inquiry, recipients, actor,
                                 messages.assigned(inquiry, job_label, actor))
        if policy.channel_on('ASSIGNED', 'email', inquiry=inquiry):
            send_notification(E.ASSIGNED, inquiry, recipients, 'inquiry_assigned', {
                'situation': '직무 배정', 'job_label': job_label,
            })
    except Exception:
        logger.exception('직무 지정 알림 실패: %s', inquiry.inquiry_no)


def notify_comment_added(comment):
    """답변 → 요청자 (웹+메일) / 사용자 코멘트 → 담당자 (웹) / 내부 메모 → 없음"""
    try:
        situation = policy.comment_situation(comment)
        inquiry, actor = comment.inquiry, comment.author
        recipients = policy.comment_recipients(comment)
        web = policy.channel_on(situation, 'web', inquiry=inquiry)
        email = policy.channel_on(situation, 'email', inquiry=inquiry)

        if comment.type == Comment.Type.ANSWER:
            if web:
                create_notifications(E.ANSWERED, inquiry, recipients, actor, messages.answered(inquiry, actor))
            if email:
                send_notification(E.ANSWERED, inquiry, recipients, 'inquiry_answered', {
                    'situation': '답변 등록',
                    'comment_body': comment.content,
                    'answered_by': messages.staff_display(actor),  # 답변자 이름 대신 직무
                })
        elif comment.type == Comment.Type.USER:
            if web:
                create_notifications(E.COMMENTED, inquiry, recipients, actor, messages.commented(inquiry, actor))
            if email:
                send_notification(E.COMMENTED, inquiry, recipients, 'inquiry_commented', {
                    'situation': '요청자 코멘트', 'comment_body': comment.content,
                })
    except Exception:
        logger.exception('답변·코멘트 알림 실패: comment %s', comment.pk)
