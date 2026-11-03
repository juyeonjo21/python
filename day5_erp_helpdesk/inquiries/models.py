"""
inquiries 앱 모델 - 문의 관리의 핵심

- Category       : 문의 분류 (권한 요청, 오류 신고 등)
- Inquiry        : 문의 본문
- Comment        : 답변·내부 메모·사용자 댓글
- History        : 처리 이력 (기록 전용, 수정·삭제 불가)
- Attachment     : 첨부파일
- RelatedInquiry : 관련 문의 연결
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from accounts.models import Job


class Category(models.Model):
    """문의 분류. parent를 지정하면 하위 분류가 됩니다."""

    name = models.CharField('분류명', max_length=50)
    parent = models.ForeignKey(
        'self',  # 자기 자신(Category)을 가리킴
        verbose_name='상위 분류',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='children',
    )
    # 분류별 추가 입력 항목 정의
    # 예: [{"key": "menu", "label": "메뉴명", "type": "text", "required": true}]
    extra_fields = models.JSONField('추가 입력 항목', default=list, blank=True)
    sort_order = models.PositiveIntegerField('정렬 순서', default=0)
    is_active = models.BooleanField('사용 여부', default=True)

    class Meta:
        verbose_name = '문의 분류'
        verbose_name_plural = '문의 분류'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f'{self.parent.name} > {self.name}' if self.parent else self.name


class Inquiry(models.Model):
    """문의"""

    class Status(models.TextChoices):
        RECEIVED = 'RECEIVED', '접수'
        CHECKING = 'CHECKING', '확인 중'
        IN_PROGRESS = 'IN_PROGRESS', '처리 중'
        ANSWERED = 'ANSWERED', '답변 완료'
        CLOSED = 'CLOSED', '처리 완료'
        ON_HOLD = 'ON_HOLD', '보류'
        REJECTED = 'REJECTED', '반려'

    class Priority(models.TextChoices):
        LOW = 'LOW', '낮음'
        NORMAL = 'NORMAL', '보통'
        HIGH = 'HIGH', '높음'
        URGENT = 'URGENT', '긴급'

    # 사유 입력이 꼭 필요한 상태
    REASON_REQUIRED_STATUSES = (Status.ON_HOLD, Status.REJECTED)

    inquiry_no = models.CharField('문의번호', max_length=20, unique=True, editable=False)
    title = models.CharField('제목', max_length=200)
    content = models.TextField('내용')
    category = models.ForeignKey(
        Category, verbose_name='분류', on_delete=models.PROTECT, related_name='inquiries'
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='요청자',
        on_delete=models.PROTECT,
        related_name='requested_inquiries',
    )
    # 요청자가 나중에 부서를 옮겨도 등록 당시 부서가 남도록 따로 저장
    department = models.ForeignKey(
        'accounts.Department',
        verbose_name='요청 부서',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='inquiries',
    )
    # 담당은 사람이 아니라 직무(백엔드/프론트/기획)로 지정. 비어 있으면 '미지정'
    assigned_job = models.CharField('담당 직무', max_length=10, choices=Job.choices, blank=True, db_index=True)
    status = models.CharField(
        '상태', max_length=20, choices=Status.choices, default=Status.RECEIVED, db_index=True
    )
    priority = models.CharField(
        '우선순위', max_length=10, choices=Priority.choices, default=Priority.NORMAL
    )
    # 분류별 추가 입력값 (Category.extra_fields에 정의된 항목의 값)
    extra_data = models.JSONField('추가 입력값', default=dict, blank=True)
    # 처리 결과 또는 보류·반려 사유
    resolution = models.TextField('처리 결과/사유', blank=True)

    created_at = models.DateTimeField('등록일시', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)
    resolved_at = models.DateTimeField('답변일시', null=True, blank=True)
    closed_at = models.DateTimeField('완료일시', null=True, blank=True)

    class Meta:
        verbose_name = '문의'
        verbose_name_plural = '문의'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.inquiry_no}] {self.title}'

    def clean(self):
        """저장 전 검사: 보류·반려는 사유가 반드시 있어야 함"""
        if self.status in self.REASON_REQUIRED_STATUSES and not self.resolution.strip():
            raise ValidationError({'resolution': '보류·반려 상태에는 사유를 반드시 입력해야 합니다.'})

    def save(self, *args, **kwargs):
        # 요청 부서가 비어 있으면 요청자의 현재 부서를 저장
        if self.department_id is None and self.requester_id:
            self.department = self.requester.department

        # 답변 완료·처리 완료가 되는 순간의 시각을 기록
        now = timezone.now()
        if self.status == self.Status.ANSWERED and self.resolved_at is None:
            self.resolved_at = now
        if self.status == self.Status.CLOSED and self.closed_at is None:
            self.closed_at = now

        # 처음 저장할 때만 문의번호를 자동으로 붙임
        if self.inquiry_no:
            return super().save(*args, **kwargs)

        # 동시에 두 건이 같은 번호를 받으면 DB의 unique 검사에 걸리므로 몇 번 다시 시도
        for _ in range(5):
            self.inquiry_no = self._next_inquiry_no()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.inquiry_no = ''
        raise IntegrityError('문의번호를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.')

    @classmethod
    def _next_inquiry_no(cls):
        """올해의 다음 문의번호를 만든다. 예: ERP-2026-0001"""
        year = timezone.localdate().year
        prefix = f'ERP-{year}-'
        last_no = (
            cls.objects.filter(inquiry_no__startswith=prefix)
            .order_by('-inquiry_no')
            .values_list('inquiry_no', flat=True)
            .first()
        )
        next_number = int(last_no.split('-')[-1]) + 1 if last_no else 1
        return f'{prefix}{next_number:04d}'


class Comment(models.Model):
    """문의에 달리는 글 (담당자 답변, 내부 메모, 사용자 댓글)"""

    class Type(models.TextChoices):
        ANSWER = 'ANSWER', '답변'               # 담당자 → 요청자에게 공개
        INTERNAL = 'INTERNAL', '내부 메모'      # 담당자끼리만 보는 메모
        USER = 'USER', '사용자 댓글'            # 요청자의 추가 문의

    inquiry = models.ForeignKey(
        Inquiry, verbose_name='문의', on_delete=models.CASCADE, related_name='comments'
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='작성자', on_delete=models.PROTECT, related_name='comments'
    )
    type = models.CharField('구분', max_length=10, choices=Type.choices, default=Type.ANSWER)
    content = models.TextField('내용')
    created_at = models.DateTimeField('작성일시', auto_now_add=True)

    class Meta:
        verbose_name = '답변/댓글'
        verbose_name_plural = '답변/댓글'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.inquiry.inquiry_no} - {self.get_type_display()} ({self.author})'


class History(models.Model):
    """
    처리 이력 - 누가 언제 무엇을 바꿨는지 남기는 기록.
    한 번 저장한 이력은 수정하거나 삭제할 수 없습니다.
    """

    class Action(models.TextChoices):
        CREATE = 'CREATE', '등록'
        STATUS = 'STATUS', '상태 변경'
        ASSIGN = 'ASSIGN', '담당자 지정'
        CATEGORY = 'CATEGORY', '분류 변경'
        PRIORITY = 'PRIORITY', '우선순위 변경'
        COMMENT = 'COMMENT', '답변 등록'

    # 이력이 있는 문의는 삭제할 수 없도록 PROTECT
    inquiry = models.ForeignKey(
        Inquiry, verbose_name='문의', on_delete=models.PROTECT, related_name='histories'
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='처리자', on_delete=models.PROTECT, related_name='histories'
    )
    action = models.CharField('구분', max_length=10, choices=Action.choices)
    from_value = models.CharField('변경 전', max_length=200, blank=True)
    to_value = models.CharField('변경 후', max_length=200, blank=True)
    memo = models.TextField('메모', blank=True)
    created_at = models.DateTimeField('일시', auto_now_add=True)

    class Meta:
        verbose_name = '처리 이력'
        verbose_name_plural = '처리 이력'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.inquiry.inquiry_no} - {self.get_action_display()}'

    def save(self, *args, **kwargs):
        # 이미 저장된 이력(pk가 있음)을 다시 저장하려 하면 막음
        if self.pk is not None:
            raise ValueError('처리 이력은 수정할 수 없습니다.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('처리 이력은 삭제할 수 없습니다.')


class Attachment(models.Model):
    """첨부파일 - 문의 자체 또는 특정 답변에 붙일 수 있음"""

    inquiry = models.ForeignKey(
        Inquiry, verbose_name='문의', on_delete=models.CASCADE, related_name='attachments'
    )
    comment = models.ForeignKey(
        Comment,
        verbose_name='답변',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='attachments',
    )
    # media/attachments/2026/11/ 같은 폴더에 저장됨
    file = models.FileField('파일', upload_to='attachments/%Y/%m/')
    original_name = models.CharField('원본 파일명', max_length=255)
    size = models.PositiveBigIntegerField('크기(byte)', default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='올린 사람', on_delete=models.PROTECT, related_name='attachments'
    )
    created_at = models.DateTimeField('업로드일시', auto_now_add=True)

    class Meta:
        verbose_name = '첨부파일'
        verbose_name_plural = '첨부파일'
        ordering = ['created_at']

    # 썸네일로 보여줄 수 있는 이미지 확장자
    IMAGE_EXTENSIONS = ('jpg', 'jpeg', 'png', 'gif', 'webp')

    def __str__(self):
        return self.original_name

    @property
    def is_image(self):
        """이미지 파일이면 True (상세 화면에서 썸네일로 표시)"""
        return self.original_name.rsplit('.', 1)[-1].lower() in self.IMAGE_EXTENSIONS

    def save(self, *args, **kwargs):
        # 원본 파일명과 크기를 자동으로 채움
        if self.file:
            if not self.original_name:
                self.original_name = self.file.name.split('/')[-1]
            if not self.size:
                self.size = self.file.size
        super().save(*args, **kwargs)


class RelatedInquiry(models.Model):
    """관련 문의 연결 (예: 같은 오류를 신고한 다른 문의)"""

    inquiry = models.ForeignKey(
        Inquiry, verbose_name='문의', on_delete=models.CASCADE, related_name='related_links'
    )
    related = models.ForeignKey(
        Inquiry, verbose_name='관련 문의', on_delete=models.CASCADE, related_name='+'
    )
    note = models.CharField('메모', max_length=200, blank=True)

    class Meta:
        verbose_name = '관련 문의'
        verbose_name_plural = '관련 문의'
        constraints = [
            # 같은 연결을 두 번 만들지 않음
            models.UniqueConstraint(fields=['inquiry', 'related'], name='unique_related_inquiry'),
            # 자기 자신과는 연결하지 않음
            models.CheckConstraint(
                condition=~models.Q(inquiry=models.F('related')), name='related_not_self'
            ),
        ]

    def __str__(self):
        return f'{self.inquiry.inquiry_no} ↔ {self.related.inquiry_no}'
