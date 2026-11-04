"""
모든 화면에 '안 읽은 웹 알림 개수'를 넘겨주는 context processor (쿼리 1번)

템플릿에서 사용:
  unread_count   : 숫자 (예: 3)
  unread_display : 화면 표시용 (99개 초과는 '99+')
"""

from .models import Notification

DISPLAY_MAX = 99


def display_count(count):
    """배지에 보일 글자: 0 → '', 120 → '99+'"""
    if not count:
        return ''
    return f'{DISPLAY_MAX}+' if count > DISPLAY_MAX else str(count)


def unread_notifications(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    count = Notification.objects.filter(recipient=user, is_read=False).count()
    return {'unread_count': count, 'unread_display': display_count(count)}
