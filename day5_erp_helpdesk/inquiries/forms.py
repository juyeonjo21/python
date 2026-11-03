"""inquiries 앱 폼"""

from django import forms

from accounts.models import Department, Job

from .models import Category, Comment, Inquiry


class InquiryFilterForm(forms.Form):
    """
    문의 목록의 검색·필터 조건 (주소의 ?q=...&category=... 값을 검사)
    잘못된 값(없는 카테고리 번호, 틀린 날짜 등)은 조건에서 빠지고 무시됩니다.
    """

    # 정렬 방식: 주소에 쓰는 값 → 화면 이름
    SORT_CHOICES = [
        ('-created', '최신 등록순'),
        ('created', '오래된 등록순'),
        ('status', '상태순'),
        ('-status', '상태 역순'),
    ]
    NO_JOB = 'none'  # 담당 직무 필터의 '미지정' 값

    q = forms.CharField(required=False, max_length=100)
    status = forms.CharField(required=False)  # 상태 탭 (view에서 허용 값 검사)
    category = forms.ModelChoiceField(queryset=Category.objects.filter(is_active=True), required=False)
    department = forms.ModelChoiceField(queryset=Department.objects.filter(is_active=True), required=False)
    # 담당 직무: 전체 / 미지정 / 백엔드 / 프론트 / 기획
    job = forms.ChoiceField(choices=[('', '전체'), (NO_JOB, '미지정')] + Job.choices, required=False)
    priority = forms.ChoiceField(choices=[('', '전체')] + Inquiry.Priority.choices, required=False)
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)
    my_job = forms.BooleanField(required=False)  # '내 직무만' (로그인한 담당자의 직무)
    sort = forms.ChoiceField(choices=SORT_CHOICES, required=False)
    # ※ is_valid() 후 cleaned_data에는 올바른 칸만 들어 있음 (틀린 칸은 Django가 자동으로 뺌)


# ============================================================
# 문의 등록
# ============================================================

# 첨부파일 제한
ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'pdf', 'xls', 'xlsx', 'doc', 'docx', 'txt']
MAX_FILE_SIZE_MB = 10
MAX_FILE_COUNT = 10

# datetime-local 입력칸이 보내는 형식 (예: 2026-11-03T14:30)
DATETIME_LOCAL_FORMAT = '%Y-%m-%dT%H:%M'


class MultipleFileInput(forms.ClearableFileInput):
    """파일 여러 개를 한 번에 고를 수 있는 입력칸"""

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """여러 파일을 받아 [파일, 파일, ...] 목록으로 돌려주는 필드"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(f, initial) for f in files if f]


def validate_attachments(files):
    """첨부파일 검사 (개수·확장자·크기). 문제가 있으면 파일별 오류를 모아서 냄"""
    files = files or []
    if len(files) > MAX_FILE_COUNT:
        raise forms.ValidationError(f'첨부파일은 최대 {MAX_FILE_COUNT}개까지 올릴 수 있습니다.')
    errors = []
    for f in files:
        ext = f.name.rsplit('.', 1)[-1].lower() if '.' in f.name else ''
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f'{f.name}: 허용되지 않는 파일 형식입니다.')
        elif f.size > MAX_FILE_SIZE_MB * 1024 * 1024:
            errors.append(f'{f.name}: 파일당 {MAX_FILE_SIZE_MB}MB까지 올릴 수 있습니다.')
    if errors:
        raise forms.ValidationError(errors)
    return files


def build_extra_field(spec):
    """
    카테고리 extra_fields의 항목 정의(JSON 1개)로 Django 입력 필드를 만든다.
    spec 예: {"key": "screen", "label": "ERP 화면명", "type": "text", "required": true,
              "placeholder": "...", "options": [...]}
    """
    kind = spec.get('type', 'text')
    common = {
        'label': spec.get('label', spec['key']),
        'required': bool(spec.get('required')),
        'help_text': spec.get('help', ''),
    }
    attrs = {'placeholder': spec.get('placeholder', '')}

    if kind == 'textarea':
        return forms.CharField(widget=forms.Textarea(attrs={**attrs, 'rows': 3}), max_length=2000, **common)
    if kind == 'select':
        choices = [('', '선택하세요')] + [(o, o) for o in spec.get('options', [])]
        return forms.ChoiceField(choices=choices, **common)
    if kind == 'number':
        return forms.IntegerField(widget=forms.NumberInput(attrs=attrs), **common)
    if kind == 'date':
        return forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'), **common)
    if kind == 'datetime':
        return forms.DateTimeField(
            widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_LOCAL_FORMAT),
            input_formats=[DATETIME_LOCAL_FORMAT],
            **common,
        )
    return forms.CharField(widget=forms.TextInput(attrs=attrs), max_length=200, **common)


class InquiryCreateForm(forms.ModelForm):
    """
    문의 등록 폼
    - 기본 항목: 카테고리, 우선순위, 제목, 내용, 첨부파일
    - 추가 항목: 선택한 카테고리의 extra_fields에 따라 'extra_<key>' 이름으로 자동 생성
    """

    EXTRA_PREFIX = 'extra_'

    attachments = MultipleFileField(label='첨부파일', required=False)

    class Meta:
        model = Inquiry
        fields = ['category', 'priority', 'title', 'content']
        widgets = {
            'category': forms.RadioSelect,
            'priority': forms.RadioSelect,
            'content': forms.Textarea(attrs={'rows': 12}),
        }
        error_messages = {
            'category': {'required': '카테고리를 선택해 주세요.'},
            'title': {'required': '제목을 입력해 주세요.'},
            'content': {'required': '내용을 입력해 주세요.'},
        }

    def __init__(self, *args, category=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.filter(is_active=True)
        self.fields['category'].empty_label = None
        self.fields['title'].widget.attrs.update({
            'placeholder': '예: 시험 접수 화면에서 저장 버튼 오류',
            'autocomplete': 'off',
        })
        self.fields['content'].widget.attrs['placeholder'] = (
            '아래 예시처럼 적어 주시면 더 빨리 처리할 수 있어요.\n\n'
            '- 어떤 화면에서: 시험 > 접수 등록\n'
            '- 무엇을 하려다가: 신규 접수를 저장하려고\n'
            '- 어떤 문제가: 저장 버튼을 누르면 오류 창이 뜹니다\n'
            '- 언제부터: 11월 3일 오전부터\n'
            '- 원하는 결과: 정상적으로 저장되었으면 합니다'
        )

        # 선택한 카테고리의 추가 항목 만들기
        self.extra_specs = [s for s in (category.extra_fields if category else []) if s.get('key')]
        for spec in self.extra_specs:
            self.fields[self.EXTRA_PREFIX + spec['key']] = build_extra_field(spec)

        # 모든 입력칸에 공통 디자인 클래스(.input) 적용 (라디오·파일 제외)
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.RadioSelect, forms.FileInput)):
                css = 'input h-auto py-2.5 leading-relaxed' if isinstance(field.widget, forms.Textarea) else 'input'
                field.widget.attrs['class'] = css

    # 템플릿에서 추가 항목만 꺼내 쓰기 위한 목록
    @property
    def extra_bound_fields(self):
        return [self[self.EXTRA_PREFIX + s['key']] for s in self.extra_specs]

    @property
    def attachment_accept(self):
        """파일 선택 창에서 허용할 확장자 (예: .jpg,.png,...)"""
        return ','.join(f'.{ext}' for ext in ALLOWED_EXTENSIONS)

    def clean_title(self):
        title = self.cleaned_data['title'].strip()
        if len(title) < 5:
            raise forms.ValidationError('제목은 5자 이상 입력해 주세요.')
        return title

    def clean_attachments(self):
        return validate_attachments(self.cleaned_data.get('attachments'))

    def get_extra_data(self):
        """추가 항목 입력값을 JSON으로 저장할 수 있는 형태로 정리 {key: 값}"""
        result = {}
        for spec in self.extra_specs:
            value = self.cleaned_data.get(self.EXTRA_PREFIX + spec['key'])
            if value in (None, ''):
                continue
            if hasattr(value, 'strftime'):  # 날짜·일시는 글자로 바꿔 저장
                value = value.strftime('%Y-%m-%d %H:%M' if spec.get('type') == 'datetime' else '%Y-%m-%d')
            result[spec['key']] = value
        return result


# ============================================================
# 상세 화면 하단 입력창 (답변·내부 메모·코멘트)
# ============================================================
class CommentForm(forms.Form):
    """종류(type)가 작성자에게 허용되는지는 services.add_comment에서 검사"""

    type = forms.ChoiceField(choices=Comment.Type.choices)
    content = forms.CharField(max_length=5000, error_messages={'required': '내용을 입력해 주세요.'})
    attachments = MultipleFileField(required=False)

    def clean_attachments(self):
        return validate_attachments(self.cleaned_data.get('attachments'))
