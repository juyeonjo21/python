"""
메일 서버 설정 확인용 시험 메일 보내기

사용법:
    python manage.py send_test_email 받는주소@회사도메인

하는 일:
  1) 지금 .env에서 읽은 메일 설정을 보여줌 (비밀번호는 가림)
  2) 메일 서버에 연결·로그인 → 시험 메일 1통 발송
  3) 실패하면 원인(인증 실패, 시간 초과, TLS 오류 등)과 해결 방법을 한국어로 알려줌
※ 받는 주소를 직접 지정하므로 EMAIL_REDIRECT_TO는 적용하지 않습니다.
※ 발송 기록(EmailLog)에는 남기지 않습니다. (알림 메일만 기록)
"""

import smtplib
import socket
import ssl
import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.management.base import BaseCommand
from django.core.validators import validate_email
from django.utils import timezone

# 실제로 보내지 않는 백엔드
FAKE_BACKENDS = {
    'django.core.mail.backends.console.EmailBackend': '콘솔(터미널 출력)',
    'notifications.backends.ReadableConsoleEmailBackend': '개발용 콘솔(터미널 출력)',
    'django.core.mail.backends.locmem.EmailBackend': '메모리(테스트용)',
    'django.core.mail.backends.filebased.EmailBackend': '파일 저장',
    'django.core.mail.backends.dummy.EmailBackend': '아무것도 안 함',
}


def explain(error):
    """오류 → (원인, 해결 방법 목록). 순서 중요: 구체적인 오류부터 검사"""
    host, port = settings.EMAIL_HOST, settings.EMAIL_PORT
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return '인증 실패 - 메일 서버가 아이디/비밀번호를 거부했습니다.', [
            'EMAIL_HOST_USER가 전체 메일 주소(예: erp-helpdesk@회사도메인)인지, 아니면 사내 계정 ID(예: 도메인\\아이디)인지 전산팀에 확인',
            'EMAIL_HOST_PASSWORD 오타·만료 확인 (2단계 인증 계정이면 앱 비밀번호 필요)',
            '해당 계정에 SMTP 인증(SMTP AUTH) 사용이 허용되어 있는지 전산팀에 확인',
        ]
    if isinstance(error, smtplib.SMTPNotSupportedError):
        return '메일 서버가 요청한 기능(STARTTLS 또는 로그인)을 지원하지 않습니다.', [
            f'포트 {port}가 암호화(STARTTLS)를 지원하는 포트인지 확인 (보통 587)',
            '사내 내부 릴레이(보통 25번, 인증 없음)라면 EMAIL_USE_TLS=False, EMAIL_HOST_USER·PASSWORD를 비워서 시도',
        ]
    if isinstance(error, smtplib.SMTPSenderRefused):
        return f'발신 주소 거부 - 서버가 보낸 사람 주소({settings.DEFAULT_FROM_EMAIL})를 받아주지 않습니다.', [
            'DEFAULT_FROM_EMAIL의 주소가 로그인 계정(EMAIL_HOST_USER)과 같은지 확인',
            '다른 주소로 보내려면 해당 계정에 "대리 발송(Send As)" 권한이 필요 (전산팀 요청)',
        ]
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return '받는 주소 거부 - 서버가 이 받는 사람에게 보내기를 거부했습니다.', [
            '받는 주소 오타 확인',
            '외부 도메인(gmail 등)으로 보낼 때만 실패한다면, 사내 서버의 "외부 릴레이" 허용이 필요 (전산팀 요청)',
        ]
    if isinstance(error, smtplib.SMTPDataError):
        return f'메일 내용 거부 - 서버가 메일을 받는 도중 거부했습니다. ({error.smtp_code})', [
            '서버의 발송 제한(분당 발송 수, 크기 제한, 스팸 정책)에 걸렸는지 전산팀에 확인',
        ]
    if isinstance(error, smtplib.SMTPServerDisconnected):
        return '서버가 연결을 끊었습니다. 대부분 암호화 방식(TLS/SSL)과 포트가 맞지 않을 때 생깁니다.', [
            '포트 465 → EMAIL_USE_SSL=True, EMAIL_USE_TLS=False',
            '포트 587 → EMAIL_USE_TLS=True, EMAIL_USE_SSL=False',
            '포트 25 → 사내 내부 릴레이인 경우가 많음 (보통 TLS·SSL 모두 False)',
        ]
    if isinstance(error, ssl.SSLCertVerificationError):
        return '보안 인증서 확인 실패 - 메일 서버 인증서를 신뢰할 수 없습니다.', [
            f'EMAIL_HOST({host})가 인증서에 적힌 서버 이름과 같은지 확인 (IP 대신 서버 이름 사용)',
            '사내 자체 인증서라면 이 서버(PC)에 회사 루트 인증서를 설치해야 함 (전산팀 요청)',
        ]
    if isinstance(error, ssl.SSLError):
        return f'TLS/SSL 암호화 연결 실패 ({error.reason or error})', [
            '포트와 암호화 설정 조합 확인: 465=SSL / 587=TLS(STARTTLS)',
            'EMAIL_USE_TLS와 EMAIL_USE_SSL은 동시에 True로 둘 수 없음',
        ]
    if isinstance(error, (socket.timeout, TimeoutError)):
        return f'연결 시간 초과 - {settings.EMAIL_TIMEOUT}초 안에 {host}:{port}에서 응답이 없습니다.', [
            '회사 방화벽이 이 PC(서버)에서 메일 포트로 나가는 연결을 막고 있는지 확인 (전산팀)',
            '사내 메일 서버라면 사내망·VPN에 연결된 상태인지 확인',
            'EMAIL_HOST와 EMAIL_PORT 오타 확인',
        ]
    if isinstance(error, ConnectionRefusedError):
        return f'연결 거부 - {host}:{port}에서 메일 서비스가 응답하지 않습니다.', [
            'EMAIL_PORT가 맞는지 확인 (25 / 465 / 587)',
            '메일 서버 주소(EMAIL_HOST)가 맞는지 확인',
        ]
    if isinstance(error, socket.gaierror):
        return f'서버 주소를 찾을 수 없습니다 - "{host}"', [
            'EMAIL_HOST 오타 확인',
            '사내 서버 이름이라면 사내망·VPN 연결 상태 확인',
        ]
    if isinstance(error, ValueError) and 'EMAIL_USE_TLS/EMAIL_USE_SSL' in str(error):
        return '설정 오류 - EMAIL_USE_TLS와 EMAIL_USE_SSL이 둘 다 True입니다.', [
            '465 포트는 SSL만, 587 포트는 TLS만 True로 설정',
        ]
    if isinstance(error, OSError):
        return f'네트워크 오류 - {error}', ['네트워크 연결과 방화벽 설정 확인']
    return f'알 수 없는 오류 - {type(error).__name__}: {error}', ['아래 오류 원문을 전산팀에 전달해 확인']


class Command(BaseCommand):
    help = '메일 서버 설정이 맞는지 시험 메일을 보내 확인합니다.'

    def add_arguments(self, parser):
        parser.add_argument('to', help='시험 메일을 받을 주소')

    def handle(self, *args, **options):
        to = options['to'].strip()
        try:
            validate_email(to)
        except ValidationError:
            self.stderr.write(self.style.ERROR(f'받는 주소 형식이 올바르지 않습니다: {to}'))
            raise SystemExit(1)

        self._print_settings(to)

        backend = settings.EMAIL_BACKEND
        if backend in FAKE_BACKENDS:
            self.stdout.write(self.style.WARNING(
                f'\n※ 지금 EMAIL_BACKEND가 "{FAKE_BACKENDS[backend]}"이라 실제로 보내지 않습니다.\n'
                '  실제 서버로 시험하려면 .env에서 EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend 로 바꾸세요.\n'
            ))

        step = '연결·로그인'
        started = time.monotonic()
        try:
            connection = get_connection(fail_silently=False)
            self.stdout.write(f'1) 메일 서버 {step} 중...')
            connection.open()
            self.stdout.write(self.style.SUCCESS(f'   완료 ({time.monotonic() - started:.1f}초)'))

            step = '발송'
            sent_started = time.monotonic()
            self.stdout.write(f'2) 시험 메일 {step} 중...')
            message = EmailMultiAlternatives(
                subject='[ERP 문의] 메일 발송 시험',
                body=self._text_body(),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to],
                connection=connection,
            )
            message.attach_alternative(self._html_body(), 'text/html')
            message.send()
            connection.close()
            self.stdout.write(self.style.SUCCESS(f'   완료 ({time.monotonic() - sent_started:.1f}초)'))
        except Exception as error:
            reason, fixes = explain(error)
            self.stdout.write(self.style.ERROR(f'\n✗ 실패 ({step} 단계, {time.monotonic() - started:.1f}초)'))
            self.stdout.write(self.style.ERROR(f'  원인: {reason}'))
            self.stdout.write('  확인할 것:')
            for fix in fixes:
                self.stdout.write(f'   - {fix}')
            self.stdout.write(f'  오류 원문: {type(error).__name__}: {error}')
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS(
            f'\n✓ 성공 - {to} 로 시험 메일을 보냈습니다. (총 {time.monotonic() - started:.1f}초)\n'
            '  받은편지함과 스팸함을 확인하세요. 스팸함에 있다면 SPF/DKIM 설정을 전산팀에 요청하세요.'
        ))

    # --------------------------------------------------------
    def _print_settings(self, to):
        password = settings.EMAIL_HOST_PASSWORD
        rows = [
            ('EMAIL_BACKEND', settings.EMAIL_BACKEND),
            ('EMAIL_HOST', settings.EMAIL_HOST),
            ('EMAIL_PORT', settings.EMAIL_PORT),
            ('EMAIL_USE_TLS', settings.EMAIL_USE_TLS),
            ('EMAIL_USE_SSL', settings.EMAIL_USE_SSL),
            ('EMAIL_HOST_USER', settings.EMAIL_HOST_USER or '(비어 있음 - 인증 없이 연결)'),
            ('EMAIL_HOST_PASSWORD', f'****** ({len(password)}자)' if password else '(비어 있음)'),
            ('EMAIL_TIMEOUT', f'{settings.EMAIL_TIMEOUT}초'),
            ('DEFAULT_FROM_EMAIL', settings.DEFAULT_FROM_EMAIL),
            ('EMAIL_REDIRECT_TO', (settings.EMAIL_REDIRECT_TO or '(비어 있음)') + ' ← 이 명령에는 적용 안 함'),
            ('받는 주소', to),
        ]
        self.stdout.write('\n현재 메일 설정 (.env)')
        for key, value in rows:
            self.stdout.write(f'  {key:<20} {value}')
        self.stdout.write('')

    def _text_body(self):
        return (
            'ERP Helpdesk 메일 발송 시험입니다.\n\n'
            f'보낸 시각: {timezone.localtime():%Y-%m-%d %H:%M:%S}\n'
            f'메일 서버: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}\n\n'
            '이 메일이 보이면 알림 메일 설정이 정상입니다.'
        )

    def _html_body(self):
        return (
            '<div style="max-width:600px;margin:0 auto;padding:24px;border:1px solid #E9E9E7;border-radius:8px;'
            'font-family:Arial,sans-serif;color:#37352F;">'
            '<p style="margin:0 0 12px;font-weight:700;">ERP Helpdesk</p>'
            '<p style="margin:0 0 8px;">메일 발송 시험입니다.</p>'
            f'<p style="margin:0;color:#787774;font-size:13px;">보낸 시각 {timezone.localtime():%Y-%m-%d %H:%M:%S} · '
            f'서버 {settings.EMAIL_HOST}:{settings.EMAIL_PORT}</p>'
            '<p style="margin:12px 0 0;">이 메일이 보이면 알림 메일 설정이 정상입니다.</p></div>'
        )
