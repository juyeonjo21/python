"""notifications 앱 화면 - 메일 발송 기록 (관리자 전용)"""

from django.core.paginator import Paginator
from django.shortcuts import render
from django.urls import reverse

from accounts.decorators import admin_required

from .models import EmailLog


@admin_required
def email_log_list(request):
    """
    메일 발송 기록 목록 - 지금은 화면 자리만 있음
    TODO (이메일 단계): 상태 필터(대기·완료·실패), 실패 건 재발송 버튼
    """
    logs = EmailLog.objects.select_related('inquiry').order_by('-created_at')
    return render(request, 'notifications/email_log_list.html', {
        'page_title': '메일 발송 기록',
        'breadcrumbs': [('홈', '/'), ('관리', reverse('dashboard:manage')), ('메일 발송 기록', None)],
        'active_menu': 'manage',
        'page_obj': Paginator(logs, 20).get_page(request.GET.get('page')),
    })
