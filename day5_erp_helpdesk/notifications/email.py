"""
이메일 실제 발송

send_notification()이 하는 일
  1) 받는 사람마다 EmailLog를 PENDING(대기)으로 만든다
  2) 메일을 보낸다 → 성공하면 SENT + 발송 시각, 실패하면 FAILED + 오류 내용
  3) 이메일 주소가 비어 있으면 보내지 않고 FAILED('이메일 주소 없음')로 남긴다
  4) 어떤 오류가 나도 밖으로 던지지 않는다 → 메일이 실패해도 문의 등록·답변은 그대로 성공
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.text import Truncator

from .models import EmailLog

logger = logging.getLogger(__name__)

PREVIEW_LENGTH = 200  # 메일에 넣는 문의 본문 미리보기 글자 수
SUBJECT_MAX = EmailLog._meta.get_field('subject').max_length  # 발송 기록의 제목 칸 길이(200)

# 메일 속 상태 배지 색 (화면의 상태 배지와 같은 색 계열, 메일 프로그램 호환을 위해 인라인 CSS로 사용)
STATUS_STYLE = {
    'RECEIVED': ('#F1F1EF', '#5A5A57'),
    'CHECKING': ('#FEF3C7', '#92400E'),
    'IN_PROGRESS': ('#DBEAFE', '#1D4ED8'),
    'ANSWERED': ('#EDE9FE', '#6D28D9'),
    'CLOSED': ('#DCFCE7', '#15803D'),
    'ON_HOLD': ('#FFEDD5', '#C2410C'),
    'REJECTED': ('#FEE2E2', '#B91C1C'),
}


def inquiry_url(inquiry):
    """메일 속 링크: SITE_URL + 문의 상세 주소 (로그인 전이면 로그인 후 이 주소로 돌아옴)"""
    return settings.SITE_URL + reverse('inquiries:detail', args=[inquiry.inquiry_no])


def build_subject(inquiry, situation):
    """제목 형식: [ERP 문의] ERP-2026-0041 답변 등록 - 비밀번호 재설정 요청"""
    subject = f'[ERP 문의] {inquiry.inquiry_no} {situation} - {inquiry.title}'
    return ' '.join(subject.split())  # 제목에 줄바꿈이 들어가지 않도록


def redirect_target(original_to, subject):
    """
    개발용 테스트 주소 돌려보내기 (.env의 EMAIL_REDIRECT_TO)
    값이 있으면 → (테스트 주소, '[원래 수신: 원래주소] 제목')
    비어 있으면 → (원래 주소, 원래 제목)  ※ 운영에서는 비워 둠
    EmailLog에는 원래 받는 사람이 기록되고, 제목 앞 표시로 돌려보낸 메일임을 알 수 있음
    """
    redirect_to = getattr(settings, 'EMAIL_REDIRECT_TO', '')
    if not redirect_to:
        return original_to, subject
    return redirect_to, f'[원래 수신: {original_to}] {subject}'


def _common_context(inquiry):
    """모든 메일에 공통으로 들어가는 문의 정보 (내부 메모·첨부·다른 사용자 개인정보는 넣지 않음)"""
    bg, fg = STATUS_STYLE.get(inquiry.status, STATUS_STYLE['RECEIVED'])
    return {
        'inquiry': inquiry,
        'status_label': inquiry.get_status_display(),
        'status_bg': bg,
        'status_fg': fg,
        'requester_name': inquiry.requester.name or inquiry.requester.username,
        'department_name': inquiry.department.name if inquiry.department else '',
        'preview': Truncator(inquiry.content).chars(PREVIEW_LENGTH),
        'url': inquiry_url(inquiry),
    }


def send_notification(event_type, inquiry, recipients, template, context):
    """
    알림 메일 발송
    - event_type: EmailLog.EventType 값 (예: 'ANSWERED')
    - recipients: 받는 사람(User) 목록 - policy.py에서 정함
    - template  : templates/emails/{template}.html / .txt
    - context   : 템플릿에 넘길 값. 'situation'은 제목의 상황 문구 (예: '답변 등록')
    """
    if not recipients:
        return
    try:
        situation = context.get('situation') or EmailLog.EventType(event_type).label
        subject = build_subject(inquiry, situation)
        base = {**_common_context(inquiry), **context, 'subject': subject}
        connection = get_connection()  # 여러 통을 보낼 때 연결 한 번만 사용
    except Exception:
        logger.exception('메일 준비 실패: %s %s', event_type, inquiry.inquiry_no)
        return

    for user in recipients:
        try:
            log = EmailLog.objects.create(
                inquiry=inquiry, to=user.email or '', subject=subject[:SUBJECT_MAX],
                event_type=event_type, status=EmailLog.Status.PENDING,
            )
        except Exception:
            logger.exception('발송 기록 생성 실패: %s', user)
            continue

        if not user.email:
            _mark(log, EmailLog.Status.FAILED, '이메일 주소 없음')
            continue

        try:
            ctx = {**base, 'recipient_name': user.name or user.username}
            text_body = render_to_string(f'emails/{template}.txt', ctx)
            html_body = render_to_string(f'emails/{template}.html', ctx)
            to, final_subject = redirect_target(user.email, subject)
            log.subject = final_subject[:SUBJECT_MAX]  # 기록: 받는 사람은 원래 주소, 제목은 실제로 보낸 제목
            message = EmailMultiAlternatives(
                subject=final_subject, body=text_body, from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to], connection=connection,
            )
            message.attach_alternative(html_body, 'text/html')
            message.send()
            _mark(log, EmailLog.Status.SENT)
        except Exception as error:  # 메일 서버 오류 등 - 기록만 하고 계속
            logger.exception('메일 발송 실패: %s → %s', subject, user.email)
            _mark(log, EmailLog.Status.FAILED, f'{type(error).__name__}: {error}'[:1000])


def _mark(log, status, error=''):
    """발송 결과 기록"""
    try:
        log.status = status
        log.error_message = error
        if status == EmailLog.Status.SENT:
            log.sent_at = timezone.now()
        log.save(update_fields=['status', 'error_message', 'sent_at', 'subject'])
    except Exception:
        logger.exception('발송 결과 기록 실패: EmailLog %s', log.pk)
