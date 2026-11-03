"""notifications 앱 모델 - 이메일 발송 기록"""

from django.db import models


class EmailLog(models.Model):
    """
    이메일 1통당 1건씩 남기는 발송 기록.
    실패하면 error_message에 원인을 남기고 retry_count를 늘려 다시 보낼 수 있습니다.
    """

    class EventType(models.TextChoices):
        CREATED = 'CREATED', '문의 등록'
        ASSIGNED = 'ASSIGNED', '담당자 지정'
        STATUS_CHANGED = 'STATUS_CHANGED', '상태 변경'
        ANSWERED = 'ANSWERED', '답변 등록'

    class Status(models.TextChoices):
        PENDING = 'PENDING', '대기'
        SENT = 'SENT', '발송 완료'
        FAILED = 'FAILED', '발송 실패'

    inquiry = models.ForeignKey(
        'inquiries.Inquiry',
        verbose_name='문의',
        on_delete=models.SET_NULL,  # 문의가 없어져도 발송 기록은 남김
        null=True,
        blank=True,
        related_name='email_logs',
    )
    to = models.EmailField('받는 사람')
    subject = models.CharField('제목', max_length=200)
    event_type = models.CharField('발송 사유', max_length=20, choices=EventType.choices)
    status = models.CharField(
        '상태', max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    error_message = models.TextField('오류 내용', blank=True)
    retry_count = models.PositiveSmallIntegerField('재시도 횟수', default=0)
    created_at = models.DateTimeField('생성일시', auto_now_add=True)
    sent_at = models.DateTimeField('발송일시', null=True, blank=True)

    class Meta:
        verbose_name = '메일 발송 기록'
        verbose_name_plural = '메일 발송 기록'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.to} - {self.subject}'
