"""
dashboard 앱 화면 - 홈, 통계, 관리, UI 키트

화면마다 넘기는 공통 값:
  page_title  : 상단 페이지 제목
  breadcrumbs : 상단 경로 표시 [(이름, 주소), ...]  마지막 항목은 주소 없이 None
  active_menu : 사이드바에서 강조할 메뉴 이름
"""

import re
from collections import Counter
from datetime import date, datetime, timedelta

from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models.functions import TruncDate, TruncMonth
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import admin_required, agent_required
from accounts.models import Department, User
from inquiries.models import Category, Inquiry
from notices.models import Notice
from notifications.models import EmailLog

S = Inquiry.Status
DONE_STATUSES = [S.CLOSED, S.REJECTED]  # 더 이상 처리할 것이 없는 상태


# ------------------------------------------------------------
# 홈
# ------------------------------------------------------------
def home(request):
    user = request.user
    today = timezone.localdate()
    context = {
        'page_title': '홈',
        'active_menu': 'home',
        'today': today,
        'pinned_notices': Notice.objects.filter(is_pinned=True).order_by('-created_at')[:3],
    }

    if user.is_staff_member:
        # 담당자·관리자: 내 직무 미완료 / 미지정 / 오늘 등록
        # (직무가 없는 관리자는 '전체 미완료'를 봄)
        open_qs = Inquiry.objects.exclude(status__in=DONE_STATUSES)
        list_url = reverse('inquiries:list')
        if user.job:
            my_open = open_qs.filter(assigned_job=user.job)
            my_title, my_href = f'내 직무({user.get_job_display()}) 미완료', f'{list_url}?my_job=1'
        else:
            my_open = open_qs
            my_title, my_href = '전체 미완료', list_url
        my_open = my_open.select_related('category', 'requester').order_by('-created_at')
        context.update({
            'my_open': my_open[:8],
            'my_title': my_title,
            'my_href': my_href,
            'cards': [
                {'title': my_title, 'value': my_open.count(), 'icon': 'user-check',
                 'description': '처리 완료·반려 제외', 'href': my_href},
                {'title': '미지정 문의', 'value': open_qs.filter(assigned_job='').count(), 'icon': 'user-x',
                 'description': '담당 직무 지정이 필요해요', 'href': f'{list_url}?job=none'},
                {'title': '오늘 등록된 문의', 'value': Inquiry.objects.filter(created_at__date=today).count(),
                 'icon': 'calendar-plus', 'description': today.strftime('%Y-%m-%d'),
                 'href': f'{list_url}?date_from={today}&date_to={today}'},
            ],
        })
    else:
        # 일반 사용자: 내 문의 상태별 건수 + 최근 5건
        mine = Inquiry.objects.filter(requester=user)
        counts = dict(mine.order_by().values_list('status').annotate(n=Count('id')))
        mine_url = reverse('inquiries:mine')
        groups = [  # 목록 화면의 상태 탭과 같은 묶음
            (S.RECEIVED, S.RECEIVED.label, [S.RECEIVED], 'inbox'),
            (S.CHECKING, S.CHECKING.label, [S.CHECKING], 'search'),
            (S.IN_PROGRESS, S.IN_PROGRESS.label, [S.IN_PROGRESS], 'loader'),
            (S.ANSWERED, S.ANSWERED.label, [S.ANSWERED], 'message-square-reply'),
            (S.CLOSED, S.CLOSED.label, [S.CLOSED], 'circle-check'),
            ('HOLD', '보류·반려', [S.ON_HOLD, S.REJECTED], 'circle-pause'),
        ]
        context.update({
            'cards': [
                {'title': label, 'value': sum(counts.get(s, 0) for s in statuses), 'icon': icon,
                 'href': f'{mine_url}?status={key}'}
                for key, label, statuses, icon in groups
            ],
            'total_mine': sum(counts.values()),
            'recent': mine.select_related('category').order_by('-created_at')[:5],
        })
    return render(request, 'dashboard/home.html', context)


# ------------------------------------------------------------
# 통계
# ------------------------------------------------------------
PERIODS = [('month', '이번 달'), ('3m', '최근 3개월'), ('year', '올해'), ('custom', '직접 지정')]

# 도넛 차트의 상태 순서·색 (상태 배지와 같은 색 계열)
# 순서는 색약·일반 시력 모두에서 이웃한 조각끼리 구분되도록 검증해서 정함
# (처리 중↔답변 완료, 보류↔반려가 붙으면 구분이 어려워 보류를 처리 중 뒤로 옮김)
STATUS_CHART = [
    (S.RECEIVED, '#8b95a7'),     # 회색
    (S.CHECKING, '#eda100'),     # 노랑
    (S.IN_PROGRESS, '#2a78d6'),  # 파랑
    (S.ON_HOLD, '#eb6834'),      # 주황
    (S.ANSWERED, '#6250d6'),     # 보라
    (S.CLOSED, '#1baf7a'),       # 초록
    (S.REJECTED, '#e34948'),     # 빨강
]

# 반복 문의 순위에서 뺄 흔한 단어
STOPWORDS = {'요청', '문의', '관련', '오류', '건', '및', '등', '좀', '부탁', '부탁드립니다', '확인', '추가'}


def _period_range(request, today):
    """기간 선택값 → (기간 키, 시작일, 종료일)"""
    period = request.GET.get('period', 'month')
    if period == '3m':
        start = (today.replace(day=1) - timedelta(days=62)).replace(day=1)  # 이번 달 포함 3개월
        return period, start, today
    if period == 'year':
        return period, today.replace(month=1, day=1), today
    if period == 'custom':
        try:
            start = date.fromisoformat(request.GET.get('start', ''))
            end = date.fromisoformat(request.GET.get('end', ''))
            if start <= end:
                return period, start, end
        except ValueError:
            pass
        return period, today.replace(day=1), today  # 잘못된 날짜면 이번 달
    return 'month', today.replace(day=1), today


@agent_required
def stats(request):
    today = timezone.localdate()
    period, start, end = _period_range(request, today)
    qs = Inquiry.objects.filter(created_at__date__gte=start, created_at__date__lte=end)

    # ── 요약 카드 ──
    total = qs.count()
    closed = qs.filter(status=S.CLOSED)
    durations = [(c - r).total_seconds() / 86400 for r, c in closed.exclude(closed_at=None).values_list('created_at', 'closed_at')]
    avg_days = round(sum(durations) / len(durations), 1) if durations else None

    # ── 추이: 기간이 두 달 이하면 일별, 그보다 길면 월별 ──
    daily = (end - start).days <= 62
    trunc = TruncDate('created_at') if daily else TruncMonth('created_at')
    raw = dict(qs.annotate(t=trunc).order_by().values_list('t').annotate(n=Count('id')))
    # 월별(TruncMonth)은 '그 달 1일 0시' 일시로 오므로 날짜로 맞춤
    raw = {(k.date() if isinstance(k, datetime) else k): v for k, v in raw.items()}
    trend_labels, trend_values = [], []
    if daily:
        day = start
        while day <= end:
            trend_labels.append(day.strftime('%m/%d'))
            trend_values.append(raw.get(day, 0))
            day += timedelta(days=1)
    else:
        month = start.replace(day=1)
        while month <= end:
            trend_labels.append(month.strftime('%Y.%m'))
            trend_values.append(raw.get(month, 0))
            month = (month + timedelta(days=32)).replace(day=1)

    # ── 카테고리별·부서별 (많은 순) ──
    by_category = list(qs.values('category__name').annotate(n=Count('id')).order_by('-n', 'category__name'))
    by_department = list(qs.values('department__name').annotate(n=Count('id')).order_by('-n', 'department__name'))

    # ── 상태별 ──
    status_counts = dict(qs.order_by().values_list('status').annotate(n=Count('id')))
    status_rows = [
        {'label': S(value).label, 'value': status_counts.get(value, 0), 'color': color,
         'percent': round(status_counts.get(value, 0) * 100 / total, 1) if total else 0}
        for value, color in STATUS_CHART
    ]

    chart_data = {
        'trend': {'labels': trend_labels, 'values': trend_values},
        'category': {'labels': [r['category__name'] for r in by_category], 'values': [r['n'] for r in by_category]},
        'department': {'labels': [r['department__name'] or '(없음)' for r in by_department], 'values': [r['n'] for r in by_department]},
        'status': {'labels': [r['label'] for r in status_rows], 'values': [r['value'] for r in status_rows],
                   'colors': [r['color'] for r in status_rows]},
    }

    return render(request, 'dashboard/stats.html', {
        'page_title': '통계',
        'breadcrumbs': [('홈', '/'), ('통계', None)],
        'active_menu': 'stats',
        'periods': PERIODS,
        'period': period,
        'start': start,
        'end': end,
        'summary': [
            {'title': '전체 문의', 'value': total, 'icon': 'inbox', 'description': f'{start:%Y-%m-%d} ~ {end:%Y-%m-%d}'},
            {'title': '미처리', 'value': qs.exclude(status__in=DONE_STATUSES).count(), 'icon': 'loader',
             'description': '처리 완료·반려 제외'},
            {'title': '처리 완료', 'value': closed.count(), 'icon': 'circle-check',
             'description': f'완료율 {round(closed.count() * 100 / total) if total else 0}%'},
            {'title': '평균 처리 기간', 'value': f'{avg_days}일' if avg_days is not None else '-', 'icon': 'timer',
             'description': '등록 → 처리 완료'},
        ],
        'trend_title': '일별 문의 추이' if daily else '월별 문의 추이',
        'trend_rows': list(zip(trend_labels, trend_values)),
        'by_category': by_category,
        'category_chart_height': max(160, 44 * len(by_category) + 30),  # 막대 수에 맞춰 높이 조절
        'by_department': by_department,
        'status_rows': status_rows,
        'total': total,
        'keywords': _repeated_keywords(qs),
        'chart_data': chart_data,
    })


def _repeated_keywords(qs, limit=10):
    """같은 카테고리 안에서 제목에 자주 나오는 단어 (2건 이상, 상위 limit개)"""
    counter = Counter()
    categories = {}
    for title, cat_id, cat_name in qs.values_list('title', 'category_id', 'category__name'):
        words = {w for w in re.findall(r'[0-9A-Za-z가-힣]{2,}', title) if w not in STOPWORDS}
        for w in words:  # 한 문의에서 같은 단어는 한 번만 셈
            counter[(cat_id, w)] += 1
        categories[cat_id] = cat_name
    list_url = reverse('inquiries:list')
    return [
        {'category': categories[cat_id], 'word': word, 'count': n,
         'href': f'{list_url}?category={cat_id}&q={word}'}
        for (cat_id, word), n in counter.most_common()
        if n >= 2
    ][:limit]


# ------------------------------------------------------------
# 관리
# ------------------------------------------------------------
@admin_required
def manage(request):
    cards = [
        {'title': '사용자', 'icon': 'users', 'href': reverse('admin:accounts_user_changelist'),
         'value': User.objects.filter(is_active=True).count(), 'description': '계정·역할·부서 관리 (Admin)'},
        {'title': '부서', 'icon': 'building-2', 'href': reverse('admin:accounts_department_changelist'),
         'value': Department.objects.filter(is_active=True).count(), 'description': '부서 추가·비활성화 (Admin)'},
        {'title': '문의 카테고리', 'icon': 'tags', 'href': reverse('admin:inquiries_category_changelist'),
         'value': Category.objects.filter(is_active=True).count(), 'description': '분류·추가 입력 항목 관리 (Admin)'},
        {'title': '공지사항', 'icon': 'megaphone', 'href': reverse('notices:list'),
         'value': Notice.objects.count(), 'description': '공지 작성·수정'},
        {'title': '문의 데이터', 'icon': 'database', 'href': reverse('admin:inquiries_inquiry_changelist'),
         'value': Inquiry.objects.count(), 'description': '원본 데이터 조회 (Admin)'},
        {'title': '메일 발송 기록', 'icon': 'mail', 'href': reverse('notifications:email_logs'),
         'value': EmailLog.objects.count(), 'description': '발송 성공·실패 내역'},
        {'title': 'UI 키트', 'icon': 'layout-grid', 'href': reverse('dashboard:ui_kit'),
         'value': '', 'description': '공통 화면 요소 미리보기'},
    ]
    return render(request, 'dashboard/manage.html', {
        'page_title': '관리',
        'breadcrumbs': [('홈', '/'), ('관리', None)],
        'active_menu': 'manage',
        'cards': cards,
    })


@admin_required
def ui_kit(request):
    """모든 공통 컴포넌트를 한 화면에서 확인하는 관리자용 페이지"""
    # 페이지 나누기 예시: 가짜 데이터 95건을 10건씩
    page_obj = Paginator(range(1, 96), 10).get_page(request.GET.get('page'))

    return render(request, 'dashboard/ui_kit.html', {
        'page_title': 'UI 키트',
        'breadcrumbs': [('홈', '/'), ('관리', reverse('dashboard:manage')), ('UI 키트', None)],
        'active_menu': 'manage',
        'statuses': Inquiry.Status.choices,
        'priorities': Inquiry.Priority.choices,
        'sample_users': User.objects.filter(is_active=True).order_by('pk')[:6],
        'page_obj': page_obj,
    })
