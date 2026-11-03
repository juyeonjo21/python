"""notices 앱 모델 - 공지사항"""

from django.conf import settings
from django.db import models


class Notice(models.Model):
    """공지사항. is_pinned=True이면 목록 맨 위에 고정됩니다."""

    class Category(models.TextChoices):
        GENERAL = 'GENERAL', '일반'
        MAINTENANCE = 'MAINTENANCE', '시스템 점검'
        UPDATE = 'UPDATE', '업데이트'
        TRAINING = 'TRAINING', '교육'

    title = models.CharField('제목', max_length=200)
    content = models.TextField('내용')
    category = models.CharField('분류', max_length=20, choices=Category.choices, blank=True)
    # 이 공지와 관련된 문의 카테고리 (문의 등록 화면의 참고 패널에 표시)
    inquiry_category = models.ForeignKey(
        'inquiries.Category',
        verbose_name='관련 문의 카테고리',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='notices',
    )
    is_pinned = models.BooleanField('상단 고정', default=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='작성자', on_delete=models.PROTECT, related_name='notices'
    )
    created_at = models.DateTimeField('등록일시', auto_now_add=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)

    class Meta:
        verbose_name = '공지사항'
        verbose_name_plural = '공지사항'
        ordering = ['-is_pinned', '-created_at']  # 고정 공지 먼저, 그다음 최신순

    def __str__(self):
        return self.title
