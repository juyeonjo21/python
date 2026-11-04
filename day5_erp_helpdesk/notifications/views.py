"""
notifications 앱 화면

웹 알림 (로그인한 사용자 누구나, 본인 알림만)
  - notification_list : 전체 알림 페이지 /notifications/
  - badge             : [HTMX] 안 읽은 개수 배지만 (60초마다 자동 갱신)
  - panel             : [HTMX] 벨을 눌렀을 때 뜨는 알림 패널 (최근 10개)
  - read_all          : 모두 읽음 (POST)
  - go                : 알림 클릭 → 읽음 처리 → 문의 상세로 이동
메일 발송 기록 (관리자 전용)
  - email_log_list
"""

from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import admin_required

from .inapp import mark_all_read, mark_read
from .models import EmailLog, Notification

E = Notification.EventType
PANEL_SIZE = 10
PAGE_SIZE = 30

# 상황별 필터 (전체 알림 페이지)
EVENT_FILTERS = [
    ('', '전체'),
    (E.CREATED, '새 문의'),
    (E.ASSIGNED, '배정'),
    (E.ANSWERED, '답변'),
    (E.COMMENTED, '코멘트'),
    (E.STATUS_CHANGED, '상태 변경'),
]


def _mine(user):
    return Notification.objects.filter(recipient=user).select_related('inquiry')


def _is_htmx(request):
    return request.headers.get('HX-Request') == 'true'


def _with_count(response, user):
    """응답 헤더에 안 읽은 개수를 실어 보냄 → 화면 스크립트가 탭 제목 숫자를 바꿈"""
    response['X-Unread-Count'] = str(Notification.objects.filter(recipient=user, is_read=False).count())
    return response


# ------------------------------------------------------------
# 배지·패널 (HTMX)
# ------------------------------------------------------------
@require_GET
def badge(request):
    """안 읽은 개수 배지 3곳(사이드바 벨, 모바일 벨, '알림' 메뉴)을 oob로 돌려줌"""
    return _with_count(render(request, 'notifications/_badges.html', {'oob': True}), request.user)


@require_GET
def panel(request):
    """벨 패널: 탭(전체/안 읽음) + 최근 10개"""
    return _render_panel(request, request.GET.get('tab'))


def _render_panel(request, tab):
    tab = 'unread' if tab == 'unread' else 'all'
    items = _mine(request.user)
    if tab == 'unread':
        items = items.filter(is_read=False)
    response = render(request, 'notifications/_panel.html', {
        'tab': tab,
        'items': items[:PANEL_SIZE],
    })
    return _with_count(response, request.user)


@require_POST
def read_all(request):
    """모두 읽음 - 패널(HTMX)에서는 패널을 다시 그리고, 일반 요청이면 원래 페이지로 돌아감"""
    count = mark_all_read(request.user)
    if _is_htmx(request):
        return _render_panel(request, request.POST.get('tab'))
    messages.success(request, f'알림 {count}건을 읽음으로 표시했습니다.' if count else '안 읽은 알림이 없습니다.')
    next_url = request.POST.get('next', '')
    # 다른 사이트 주소로 돌려보내지 않도록 우리 사이트 주소일 때만 사용
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('notifications:list')
    return redirect(next_url)


# ------------------------------------------------------------
# 알림 클릭 → 문의 상세
# ------------------------------------------------------------
def go(request, pk):
    """
    본인 알림인지 확인(아니면 404) → 읽음 처리 → 문의 상세로 이동
    문의가 삭제되었거나 지금은 볼 권한이 없으면 알림 목록으로 돌아가 안내
    """
    notification = get_object_or_404(Notification.objects.select_related('inquiry'), pk=pk, recipient=request.user)
    mark_read(request.user, notification)
    inquiry = notification.inquiry
    if inquiry is None:
        messages.warning(request, '삭제된 문의라서 열 수 없습니다.')
        return redirect('notifications:list')
    if not (request.user.is_staff_member or inquiry.requester_id == request.user.id):
        messages.warning(request, f'{inquiry.inquiry_no} 문의를 볼 권한이 없습니다.')
        return redirect('notifications:list')
    return redirect('inquiries:detail', inquiry_no=inquiry.inquiry_no)


# ------------------------------------------------------------
# 전체 알림 페이지
# ------------------------------------------------------------
def notification_list(request):
    user = request.user
    tab = 'unread' if request.GET.get('tab') == 'unread' else 'all'
    event = request.GET.get('event', '')
    if event not in E.values:
        event = ''

    base = _mine(user)
    if event:
        base = base.filter(event_type=event)
    items = base.filter(is_read=False) if tab == 'unread' else base
    page_obj = Paginator(items, PAGE_SIZE).get_page(request.GET.get('page'))

    def url(**changes):
        params = {'tab': tab if tab == 'unread' else '', 'event': event, **changes}
        query = '&'.join(f'{k}={v}' for k, v in params.items() if v)
        return reverse('notifications:list') + (f'?{query}' if query else '')

    return render(request, 'notifications/notification_list.html', {
        'page_title': '알림',
        'breadcrumbs': [('홈', '/'), ('알림', None)],
        'active_menu': 'notifications',
        'tab': tab,
        'event': event,
        'tabs': [
            {'label': '전체', 'count': base.count(), 'url': url(tab=''), 'active': tab == 'all'},
            {'label': '안 읽음', 'count': base.filter(is_read=False).count(), 'url': url(tab='unread'), 'active': tab == 'unread'},
        ],
        'filters': [{'label': label, 'url': url(event=value), 'active': value == event} for value, label in EVENT_FILTERS],
        'groups': _group_by_date(page_obj.object_list),
        'page_obj': page_obj,
    })


def _group_by_date(notifications):
    """오늘 / 어제 / 이번 주(월요일부터) / 이전 으로 묶기 → [(이름, [알림, ...]), ...]"""
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())  # 이번 주 월요일
    order = ['오늘', '어제', '이번 주', '이전']
    groups = {name: [] for name in order}
    for n in notifications:
        day = timezone.localtime(n.created_at).date()
        if day == today:
            groups['오늘'].append(n)
        elif day == yesterday:
            groups['어제'].append(n)
        elif day >= week_start:
            groups['이번 주'].append(n)
        else:
            groups['이전'].append(n)
    return [(name, groups[name]) for name in order if groups[name]]


# ------------------------------------------------------------
# 메일 발송 기록 (관리자)
# ------------------------------------------------------------
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
