"""inquiries 앱 화면"""

import re
from urllib.parse import urlencode, urlparse

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_POST

from accounts.decorators import agent_required
from accounts.models import Job
from notices.models import Notice
from notifications.inapp import mark_inquiry_read

from . import services
from .forms import ALLOWED_EXTENSIONS, CommentForm, InquiryCreateForm, InquiryFilterForm
from .models import Attachment, Category, Comment, History, Inquiry, RelatedInquiry

S = Inquiry.Status

# 상태 탭: (주소의 status 값, 탭 이름, 포함되는 상태들)
STATUS_TABS = [
    ('', '전체', None),
    (S.RECEIVED, S.RECEIVED.label, [S.RECEIVED]),
    (S.CHECKING, S.CHECKING.label, [S.CHECKING]),
    (S.IN_PROGRESS, S.IN_PROGRESS.label, [S.IN_PROGRESS]),
    (S.ANSWERED, S.ANSWERED.label, [S.ANSWERED]),
    (S.CLOSED, S.CLOSED.label, [S.CLOSED]),
    ('HOLD', '보류·반려', [S.ON_HOLD, S.REJECTED]),
]

# 상태 정렬은 글자순이 아니라 처리 흐름 순서(접수 → 확인 중 → … → 반려)
STATUS_ORDER = Case(
    *[When(status=value, then=index) for index, value in enumerate(S.values)],
    output_field=IntegerField(),
)
SORT_FIELDS = {
    '-created': ['-created_at'],
    'created': ['created_at'],
    'status': ['status_order', '-created_at'],
    '-status': ['-status_order', '-created_at'],
}

# 주소에 남길 수 있는 검색 조건 이름
FILTER_KEYS = ['q', 'category', 'department', 'job', 'priority',
               'date_from', 'date_to', 'my_job']
URL_KEYS = ['status', *FILTER_KEYS, 'sort', 'page']

PAGE_SIZE = 20


# ------------------------------------------------------------
# 목록 화면
# ------------------------------------------------------------
@agent_required  # 담당자·관리자만
def inquiry_list(request):
    """전체 문의"""
    return _inquiry_list(request, scope='all')


def my_inquiries(request):
    """내 문의 (내가 요청한 문의만)"""
    return _inquiry_list(request, scope='mine')


def _inquiry_list(request, scope):
    user = request.user
    is_all = scope == 'all'

    # 1) 볼 수 있는 문의 범위 정하기 (권한)
    base = Inquiry.objects.select_related('category', 'requester', 'department')
    if not is_all:
        base = base.filter(requester=user)

    # 2) 주소의 검색 조건 읽기 (잘못된 값은 무시)
    form = InquiryFilterForm(request.GET)
    form.is_valid()
    data = form.cleaned_data
    if not is_all or not user.job:  # '내 문의'에서는 부서·내 직무 조건을 쓰지 않음 (직무가 없으면 '내 직무만'도 없음)
        data.pop('my_job', None)
    if not is_all:
        data.pop('department', None)

    # 3) 검색·필터 적용 (상태 탭은 아직 적용하지 않음 → 탭별 건수 계산용)
    filtered = _apply_filters(base, data, user)

    # 4) 탭별 건수: 상태별로 묶어서 한 번에 셈
    counts = dict(filtered.order_by().values_list('status').annotate(n=Count('id')))
    current_status = data.get('status', '')
    if current_status not in {key for key, _, _ in STATUS_TABS}:
        current_status = ''

    params = _clean_params(request.GET)
    if not is_all:
        params.pop('department', None)
        params.pop('my_job', None)
    tabs = []
    for key, label, statuses in STATUS_TABS:
        total = sum(counts.values()) if statuses is None else sum(counts.get(s, 0) for s in statuses)
        tabs.append({
            'label': label,
            'count': total,
            'url': _build_url(request.path, params, status=key, page=None),
            'active': key == current_status,
        })

    # 5) 현재 탭 적용 + 정렬 + 페이지 나누기
    inquiries = filtered
    tab_statuses = dict((key, s) for key, _, s in STATUS_TABS)[current_status]
    if tab_statuses:
        inquiries = inquiries.filter(status__in=tab_statuses)
    sort = data.get('sort') or '-created'
    inquiries = inquiries.annotate(status_order=STATUS_ORDER).order_by(*SORT_FIELDS[sort])
    page_obj = Paginator(inquiries, PAGE_SIZE).get_page(request.GET.get('page'))

    chips = _build_chips(request.path, params, data, form)
    context = {
        'page_title': '전체 문의' if is_all else '내 문의',
        'breadcrumbs': [('홈', '/'), ('전체 문의' if is_all else '내 문의', None)],
        'active_menu': scope,
        'is_all': is_all,
        'form': form,
        'data': data,
        'current_status': current_status,
        'sort': sort,
        'tabs': tabs,
        'chips': chips,
        'has_filters': bool(chips),
        'reset_url': _build_url(request.path, {k: v for k, v in params.items() if k in ('status', 'sort')}),
        'sort_urls': {
            'created': _build_url(request.path, params, sort='created' if sort == '-created' else '-created', page=None),
            'status': _build_url(request.path, params, sort='-status' if sort == 'status' else 'status', page=None),
        },
        'page_obj': page_obj,
        'total_count': page_obj.paginator.count,
    }

    # HTMX 요청(필터 변경 등)이면 목록 영역만, 아니면 화면 전체를 보냄
    is_htmx = request.headers.get('HX-Request') == 'true' and not request.headers.get('HX-History-Restore-Request')
    if is_htmx:
        context['is_htmx'] = True
        response = render(request, 'inquiries/_list_region.html', context)
        # 주소창에 빈 조건이 빠진 깔끔한 주소를 남김 → 새로고침·공유해도 같은 화면
        response['HX-Push-Url'] = _build_url(request.path, params)
    else:
        response = render(request, 'inquiries/inquiry_list.html', context)
    # 같은 주소라도 HTMX 여부에 따라 응답이 다르다는 것을 브라우저 캐시에 알림
    patch_vary_headers(response, ['HX-Request'])
    return response


def _apply_filters(queryset, data, user):
    """검색 조건을 하나씩 queryset에 적용"""
    if q := data.get('q', '').strip():
        queryset = queryset.filter(
            Q(title__icontains=q) | Q(content__icontains=q) | Q(inquiry_no__icontains=q)
        )
    if data.get('category'):
        queryset = queryset.filter(category=data['category'])
    if data.get('department'):
        queryset = queryset.filter(department=data['department'])
    if job := data.get('job'):
        queryset = queryset.filter(assigned_job='' if job == InquiryFilterForm.NO_JOB else job)
    if data.get('priority'):
        queryset = queryset.filter(priority=data['priority'])
    if data.get('date_from'):
        queryset = queryset.filter(created_at__date__gte=data['date_from'])
    if data.get('date_to'):
        queryset = queryset.filter(created_at__date__lte=data['date_to'])
    if data.get('my_job') and user.job:
        queryset = queryset.filter(assigned_job=user.job)
    return queryset


def _clean_params(querydict):
    """주소의 조건 중 우리가 쓰는 이름이면서 값이 있는 것만 남김"""
    return {key: querydict.get(key) for key in URL_KEYS if querydict.get(key)}


def _build_url(path, params, **changes):
    """
    현재 조건(params)에 일부만 바꾼 주소를 만든다.
    예) _build_url('/inquiries/', {'q': '권한'}, status='CLOSED')  →  /inquiries/?q=권한&status=CLOSED
        값을 None이나 ''로 주면 그 조건은 빠짐
    """
    merged = {**params, **changes}
    query = urlencode({k: v for k, v in merged.items() if v not in (None, '')})
    return f'{path}?{query}' if query else path


def _build_chips(path, params, data, form):
    """선택된 필터를 칩으로 표시하기 위한 목록 [{label, remove_url}]"""
    chips = []

    def add(label, *keys):
        chips.append({
            'label': label,
            'remove_url': _build_url(path, params, page=None, **{k: None for k in keys}),
        })

    if data.get('q', '').strip():
        add(f"키워드: {data['q'].strip()}", 'q')
    if data.get('category'):
        add(f"카테고리: {data['category'].name}", 'category')
    if data.get('department'):
        add(f"부서: {data['department'].name}", 'department')
    if data.get('job'):
        add(f"담당: {dict(form.fields['job'].choices)[data['job']]}", 'job')
    if data.get('priority'):
        add(f"우선순위: {Inquiry.Priority(data['priority']).label}", 'priority')
    if data.get('date_from') or data.get('date_to'):
        start = data.get('date_from') or ''
        end = data.get('date_to') or ''
        add(f'기간: {start} ~ {end}', 'date_from', 'date_to')
    if data.get('my_job'):
        add('내 직무만', 'my_job')
    return chips


# ------------------------------------------------------------
# 문의 상세
# ------------------------------------------------------------
# History에는 상태를 '접수' 같은 이름으로 저장하므로, 배지 표시용으로 이름 → 코드 변환
STATUS_BY_LABEL = {label: value for value, label in S.choices}


def _get_inquiry_for(user, inquiry_no):
    """
    문의 1건을 가져온다. 볼 권한이 없으면 404 (있다는 사실도 숨김)
    - 담당자·관리자: 모든 문의 / 일반 사용자: 본인 문의만
    """
    inquiry = get_object_or_404(
        Inquiry.objects.select_related('category', 'requester', 'department'),
        inquiry_no=inquiry_no,
    )
    if not (user.is_staff_member or inquiry.requester_id == user.id):
        raise Http404
    return inquiry


def inquiry_detail(request, inquiry_no):
    inquiry = _get_inquiry_for(request.user, inquiry_no)
    mark_inquiry_read(request.user, inquiry)  # 이 문의에 대한 내 안 읽은 웹 알림 → 읽음
    context = _detail_context(request, inquiry)
    context['back_url'] = _list_back_url(request)
    return render(request, 'inquiries/inquiry_detail.html', context)


def _list_back_url(request):
    """
    '목록으로' 버튼 주소
    목록에서 필터를 걸고 들어왔다면 그 조건 그대로 돌아감 (직전 페이지 주소 = Referer 사용)
    그 외에는 담당자·관리자 → 전체 문의, 일반 사용자 → 내 문의
    """
    allowed = [reverse('inquiries:mine')]
    if request.user.is_staff_member:
        allowed.append(reverse('inquiries:list'))
    referer = urlparse(request.META.get('HTTP_REFERER', ''))
    if referer.netloc == request.get_host() and referer.path in allowed:
        return referer.path + (f'?{referer.query}' if referer.query else '')
    return allowed[-1]


@agent_required
@require_POST
def inquiry_update(request, inquiry_no):
    """
    [HTMX] 우측 속성 패널에서 값 하나를 바꿈 (field = status / assigned_job / category / priority)
    응답: 속성 패널 + 타임라인·상단 상태 배지(oob)
    """
    user = request.user
    inquiry = _get_inquiry_for(user, inquiry_no)
    field = request.POST.get('field')
    error = None
    try:
        if field == 'status':
            services.change_status(inquiry, user, request.POST.get('status', ''), request.POST.get('reason', ''))
        elif field == 'assigned_job':
            job = request.POST.get('assigned_job', '')
            if job == 'mine':  # '내 직무로 지정' 버튼
                if not user.job:
                    raise ValidationError('내 직무가 설정되어 있지 않습니다. 관리자에게 문의하세요.')
                job = user.job
            services.assign(inquiry, user, job)
        elif field == 'category':
            value = request.POST.get('category', '')
            services.change_category(inquiry, user, Category.objects.filter(pk=value).first() if value.isdigit() else None)
        elif field == 'priority':
            services.change_priority(inquiry, user, request.POST.get('priority', ''))
        else:
            raise ValidationError('잘못된 요청입니다.')
    except ValidationError as e:
        error = e.messages[0]
        inquiry.refresh_from_db()

    context = _detail_context(request, inquiry)
    context.update({
        'panel_error': error,
        'error_field': field,
        # 상태 변경이 실패하면 사유 입력칸을 열어 둔 채로 다시 보여줌
        'pending_status': request.POST.get('status') if error and field == 'status' else '',
        'pending_reason': request.POST.get('reason', '') if error else '',
    })
    return render(request, 'inquiries/_detail_update.html', context)


@require_POST
def comment_create(request, inquiry_no):
    """
    [HTMX] 하단 입력창: 답변·내부 메모·사용자 코멘트 등록
    응답: 타임라인 + 속성 패널·상단 상태 배지·입력창 오류(oob)
    성공하면 HX-Trigger: commentAdded → 화면에서 입력창 비움
    """
    user = request.user
    inquiry = _get_inquiry_for(user, inquiry_no)
    form = CommentForm(request.POST, request.FILES)
    error = None
    if form.is_valid():
        try:
            services.add_comment(
                inquiry, user, form.cleaned_data['type'], form.cleaned_data['content'],
                files=form.cleaned_data['attachments'],
            )
        except ValidationError as e:
            error = e.messages[0]
    else:
        error = ' '.join(msg for msgs in form.errors.values() for msg in msgs)
    inquiry.refresh_from_db()

    if request.headers.get('HX-Request') != 'true':  # 자바스크립트 없이 보낸 경우
        (messages.error if error else messages.success)(request, error or '등록했습니다.')
        return redirect('inquiries:detail', inquiry_no=inquiry.inquiry_no)

    context = _detail_context(request, inquiry)
    context['composer_error'] = error
    response = render(request, 'inquiries/_comment_result.html', context)
    if not error:
        response['HX-Trigger'] = 'commentAdded'
    return response


def attachment_download(request, pk):
    """첨부파일 다운로드 - 문의를 볼 수 있는 사람만 (내부 메모의 첨부는 담당자·관리자만)"""
    attachment, file = _open_attachment(request, pk)
    return FileResponse(file, as_attachment=True, filename=attachment.original_name)


def attachment_view(request, pk):
    """
    이미지 첨부를 다운로드하지 않고 브라우저에서 바로 보여줌 (썸네일·크게 보기용)
    권한 검사는 다운로드와 같음. 이미지가 아닌 파일은 404 (HTML 등을 바로 열지 않도록)
    """
    attachment, file = _open_attachment(request, pk)
    if not attachment.is_image:
        file.close()
        raise Http404
    response = FileResponse(file, as_attachment=False, filename=attachment.original_name)
    response['Cache-Control'] = 'private, max-age=3600'  # 로그인한 본인 브라우저에만 잠시 저장
    return response


def _open_attachment(request, pk):
    """첨부파일 권한 검사 후 파일을 열어서 돌려줌"""
    attachment = get_object_or_404(Attachment.objects.select_related('inquiry', 'comment'), pk=pk)
    _get_inquiry_for(request.user, attachment.inquiry.inquiry_no)
    if (attachment.comment and attachment.comment.type == Comment.Type.INTERNAL
            and not request.user.is_staff_member):
        raise Http404
    try:
        return attachment, attachment.file.open('rb')
    except FileNotFoundError:
        raise Http404('파일을 찾을 수 없습니다.')


def _detail_context(request, inquiry):
    """상세 화면과 HTMX 부분 응답이 함께 쓰는 값"""
    user = request.user
    is_staff = user.is_staff_member

    # 카테고리 정의 순서대로 추가 항목 표시 (정의에 없는 값도 빠뜨리지 않음)
    extra_data = dict(inquiry.extra_data or {})
    extra_items = []
    for spec in inquiry.category.extra_fields or []:
        if spec.get('key') in extra_data:
            extra_items.append((spec.get('label', spec['key']), extra_data.pop(spec['key'])))
    # 남은 값 = 카테고리를 바꾸기 전에 입력한 항목 → 다른 카테고리 정의에서 이름표를 찾아 표시
    if extra_data:
        labels = {s['key']: s.get('label', s['key'])
                  for c in Category.objects.all() for s in (c.extra_fields or []) if s.get('key')}
        extra_items += [(labels.get(key, key), value) for key, value in extra_data.items()]

    # 관련 문의 (양쪽 방향 연결 모두). 일반 사용자는 본인 문의만
    links = RelatedInquiry.objects.filter(Q(inquiry=inquiry) | Q(related=inquiry)).select_related('inquiry', 'related')
    related = []
    for link in links:
        other = link.related if link.inquiry_id == inquiry.pk else link.inquiry
        if is_staff or other.requester_id == user.id:
            related.append({'inquiry': other, 'note': link.note})

    breadcrumb = ('전체 문의', reverse('inquiries:list')) if is_staff else ('내 문의', reverse('inquiries:mine'))
    return {
        'page_title': inquiry.title,
        'breadcrumbs': [('홈', '/'), breadcrumb, (inquiry.inquiry_no, None)],
        'active_menu': 'all' if is_staff else 'mine',
        'inquiry': inquiry,
        'can_edit': is_staff,
        'extra_items': extra_items,
        'attachments': inquiry.attachments.filter(comment__isnull=True),
        'timeline': _build_timeline(inquiry, user),
        'comment_types': services.allowed_comment_types(user),
        'attachment_accept': ','.join(f'.{ext}' for ext in ALLOWED_EXTENSIONS),
        'statuses': S.choices,
        'priorities': Inquiry.Priority.choices,
        'categories': Category.objects.filter(Q(is_active=True) | Q(pk=inquiry.category_id)),
        'jobs': Job.choices,
        'similar': _find_similar(user, inquiry.title, category=inquiry.category, exclude=inquiry),
        'related': related,
    }


def _build_timeline(inquiry, user):
    """답변·코멘트(Comment)와 처리 이력(History)을 시간순 하나의 목록으로 합침"""
    comments = inquiry.comments.select_related('author').prefetch_related('attachments')
    if not user.is_staff_member:
        comments = comments.exclude(type=Comment.Type.INTERNAL)  # 내부 메모 숨김
    # '답변 등록' 이력은 답변 카드와 내용이 겹치므로 타임라인에서는 생략
    histories = inquiry.histories.select_related('actor').exclude(action=History.Action.COMMENT)

    items = [{'kind': 'comment', 'obj': c, 'at': c.created_at} for c in comments]
    for h in histories:
        items.append({
            'kind': 'history', 'obj': h, 'at': h.created_at,
            'from_status': STATUS_BY_LABEL.get(h.from_value, ''),
            'to_status': STATUS_BY_LABEL.get(h.to_value, ''),
        })
    # 최신순: 상세 화면에서 입력창 바로 아래에 진행 내역이 있으므로 방금 등록한 글이 맨 위에 보이게
    return sorted(items, key=lambda item: item['at'], reverse=True)


def _find_similar(user, title, category=None, exclude=None, limit=5):
    """
    제목을 단어로 나눠(2글자 이상) 겹치는 단어가 많은 순으로 비슷한 문의를 찾음
    - category를 주면 같은 카테고리에서만, exclude를 주면 그 문의는 제외
    - 일반 사용자는 본인 문의에서만 찾음
    """
    words = [w for w in re.split(r'\s+', (title or '').strip()) if len(w) >= 2][:5]
    if not words:
        return []
    query = Q()
    for w in words:
        query |= Q(title__icontains=w)
    qs = Inquiry.objects.filter(query).select_related('category')
    if category:
        qs = qs.filter(category=category)
    if exclude:
        qs = qs.exclude(pk=exclude.pk)
    if not user.is_staff_member:
        qs = qs.filter(requester=user)
    score = sum((Case(When(title__icontains=w, then=1), default=0, output_field=IntegerField())
                 for w in words), Value(0))
    return list(qs.annotate(score=score).order_by('-score', '-created_at')[:limit])


# ------------------------------------------------------------
# 문의 등록
# ------------------------------------------------------------
# 카테고리 카드에 보여줄 아이콘·설명 (이름으로 찾고, 없으면 기본값)
CATEGORY_META = {
    '권한 요청': ('key-round', '메뉴·기능 사용 권한이 필요할 때'),
    '오류 신고': ('bug', '화면 오류나 데이터 이상이 있을 때'),
    '개선 요청': ('lightbulb', '기능 추가·변경을 제안할 때'),
    '기타 요청': ('message-circle-question', '그 밖의 문의'),
}
SIMILAR_LIMIT = 5
NOTICE_LIMIT = 5


def inquiry_create(request):
    category = _selected_category(request.POST if request.method == 'POST' else request.GET)

    if request.method == 'POST':
        form = InquiryCreateForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data
            inquiry = services.create_inquiry(
                requester=request.user,
                category=data['category'],
                priority=data['priority'],
                title=data['title'],
                content=data['content'],
                files=data['attachments'],
            )
            messages.success(request, f'문의가 접수되었습니다 ({inquiry.inquiry_no})')
            return redirect('inquiries:detail', inquiry_no=inquiry.inquiry_no)
    else:
        form = InquiryCreateForm(initial={'category': category})

    # 제목을 입력하면 0.5초 뒤 참고 패널(유사 문의)을 HTMX로 갱신
    form.fields['title'].widget.attrs.update({
        'hx-get': reverse('inquiries:create_reference'),
        'hx-trigger': 'input changed delay:500ms',
        'hx-target': '#reference-panel',
        'hx-swap': 'outerHTML',
        'hx-include': '[name=category]',
    })
    categories = [
        {'obj': c, 'icon': CATEGORY_META.get(c.name, ('tag', ''))[0], 'desc': CATEGORY_META.get(c.name, ('tag', ''))[1]}
        for c in form.fields['category'].queryset
    ]
    return render(request, 'inquiries/inquiry_form.html', {
        'page_title': '새 문의',
        'breadcrumbs': [('홈', '/'), ('새 문의', None)],
        'active_menu': 'create',
        'form': form,
        'categories': categories,
        'selected_category': category,
        'priorities': Inquiry.Priority.choices,
        # POST로 다시 열렸는데 파일을 골랐었다면 → 브라우저가 파일을 다시 채울 수 없으니 안내
        'files_lost': request.method == 'POST' and bool(request.FILES),
        **_reference_context(request.user, category, request.POST.get('title', '')),
    })


def inquiry_reference(request):
    """[HTMX] 카테고리를 고르거나 제목을 입력하면: 참고 패널(관련 공지 + 유사 문의)을 돌려줌"""
    category = _selected_category(request.GET)
    return render(request, 'inquiries/_reference_panel.html', {
        'selected_category': category,
        **_reference_context(request.user, category, request.GET.get('title', '')),
    })


def _selected_category(params):
    """요청 값의 category 번호로 활성 카테고리를 찾음 (없거나 잘못되면 None)"""
    value = params.get('category', '')
    if not value.isdigit():
        return None
    return Category.objects.filter(pk=value, is_active=True).first()


def _reference_context(user, category, title):
    """참고 패널 내용: 관련 공지사항 + 유사한 과거 문의"""
    # 공지: 선택한 카테고리 관련 공지 먼저, 그다음 상단 고정 공지
    condition = Q(is_pinned=True)
    if category:
        condition |= Q(inquiry_category=category)
    notices = (
        Notice.objects.filter(condition)
        .annotate(is_related=Case(When(inquiry_category=category, then=1), default=0,
                                  output_field=IntegerField()) if category else Value(0))
        .order_by('-is_related', '-is_pinned', '-created_at')[:NOTICE_LIMIT]
    )

    return {
        'ref_notices': notices,
        'ref_similar': _find_similar(user, title, limit=SIMILAR_LIMIT),
        'ref_title': title.strip(),
    }
