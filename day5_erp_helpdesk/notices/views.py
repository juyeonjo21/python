"""
notices 앱 화면 - 공지사항 목록·상세·작성·수정
- 목록·상세: 로그인한 모든 사용자
- 작성·수정: 담당자·관리자만
"""

from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import patch_vary_headers

from accounts.decorators import agent_required

from .forms import NoticeForm
from .models import Notice

PAGE_SIZE = 15


def notice_list(request):
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    if category not in Notice.Category.values:
        category = ''

    notices = Notice.objects.select_related('author', 'inquiry_category')  # 고정 공지 먼저 (Meta.ordering)
    if q:
        notices = notices.filter(Q(title__icontains=q) | Q(content__icontains=q))
    if category:
        notices = notices.filter(category=category)

    context = {
        'page_title': '공지사항',
        'breadcrumbs': [('홈', '/'), ('공지사항', None)],
        'active_menu': 'notices',
        'q': q,
        'category': category,
        'categories': Notice.Category.choices,
        'has_filters': bool(q or category),
        'page_obj': Paginator(notices, PAGE_SIZE).get_page(request.GET.get('page')),
    }

    # HTMX(검색·분류 변경)면 목록 부분만 보냄 + 주소창에 조건 반영
    if request.headers.get('HX-Request') == 'true' and not request.headers.get('HX-History-Restore-Request'):
        response = render(request, 'notices/_list_results.html', context)
        params = {k: v for k, v in {'q': q, 'category': category, 'page': request.GET.get('page')}.items() if v}
        response['HX-Push-Url'] = reverse('notices:list') + (f'?{urlencode(params)}' if params else '')
    else:
        response = render(request, 'notices/notice_list.html', context)
    patch_vary_headers(response, ['HX-Request'])
    return response


def notice_detail(request, pk):
    notice = get_object_or_404(Notice.objects.select_related('author', 'inquiry_category'), pk=pk)
    return render(request, 'notices/notice_detail.html', {
        'page_title': notice.title,
        'breadcrumbs': [('홈', '/'), ('공지사항', reverse('notices:list')), ('상세', None)],
        'active_menu': 'notices',
        'notice': notice,
    })


@agent_required
def notice_create(request):
    form = NoticeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        notice = form.save(commit=False)
        notice.author = request.user
        notice.save()
        messages.success(request, '공지를 등록했습니다.')
        return redirect('notices:detail', pk=notice.pk)
    return render(request, 'notices/notice_form.html', {
        'page_title': '공지 작성',
        'breadcrumbs': [('홈', '/'), ('공지사항', reverse('notices:list')), ('작성', None)],
        'active_menu': 'notices',
        'form': form,
        'cancel_url': reverse('notices:list'),
    })


@agent_required
def notice_update(request, pk):
    notice = get_object_or_404(Notice, pk=pk)
    form = NoticeForm(request.POST or None, instance=notice)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, '공지를 수정했습니다.')
        return redirect('notices:detail', pk=notice.pk)
    return render(request, 'notices/notice_form.html', {
        'page_title': '공지 수정',
        'breadcrumbs': [('홈', '/'), ('공지사항', reverse('notices:list')),
                        (notice.title, reverse('notices:detail', args=[notice.pk])), ('수정', None)],
        'active_menu': 'notices',
        'form': form,
        'notice': notice,
        'cancel_url': reverse('notices:detail', args=[notice.pk]),
    })
