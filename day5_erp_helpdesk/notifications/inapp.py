"""
웹 알림(사이트 안 알림) 만들기·읽음 처리

- create_notifications(): 받는 사람마다 알림 1건씩 한 번에(bulk_create) 만듦
  실패해도 오류를 밖으로 던지지 않음 → 문의 등록·답변, 이메일 발송에 영향 없음
- mark_read / mark_all_read / mark_inquiry_read: 읽음 처리 (본인 알림만)
"""

import logging

from django.utils import timezone

from .models import Notification

logger = logging.getLogger(__name__)


def create_notifications(event_type, inquiry, recipients, actor, message):
    """받는 사람(User) 목록에게 같은 알림을 만들고, 만든 개수를 돌려줌 (실패하면 0)"""
    if not recipients:
        return 0
    try:
        created = Notification.objects.bulk_create([
            Notification(recipient=user, inquiry=inquiry, actor=actor, event_type=event_type, message=message)
            for user in recipients
        ])
        return len(created)
    except Exception:
        logger.exception('웹 알림 생성 실패: %s %s', event_type, getattr(inquiry, 'inquiry_no', ''))
        return 0


def _unread(user):
    return Notification.objects.filter(recipient=user, is_read=False)


def mark_read(user, notification):
    """알림 1건 읽음 처리 (남의 알림이면 아무것도 하지 않음). 처리한 개수(0/1)를 돌려줌"""
    return _unread(user).filter(pk=notification.pk).update(is_read=True, read_at=timezone.now())


def mark_all_read(user):
    """내 안 읽은 알림 모두 읽음 처리"""
    return _unread(user).update(is_read=True, read_at=timezone.now())


def mark_inquiry_read(user, inquiry):
    """특정 문의에 대한 내 안 읽은 알림을 읽음 처리 (문의 상세를 열 때 호출)"""
    if not user.is_authenticated:
        return 0
    return _unread(user).filter(inquiry=inquiry).update(is_read=True, read_at=timezone.now())
