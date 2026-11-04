"""
개발용 이메일 백엔드 - 실제로 보내지 않고 터미널에 '읽기 좋게' 출력

Django 기본 콘솔 백엔드는 메일 원본을 그대로 출력해서
한글 제목이 =?utf-8?b?...?= 처럼 보입니다. 이 백엔드는 받는 사람·제목·텍스트 본문을
그대로 풀어서 보여줍니다. (HTML 본문은 길어서 글자 수만 표시)

사용: .env 에 EMAIL_BACKEND=notifications.backends.ReadableConsoleEmailBackend
"""

from django.core.mail.backends.console import EmailBackend as ConsoleEmailBackend


class ReadableConsoleEmailBackend(ConsoleEmailBackend):
    def write_message(self, message):
        html_length = sum(len(content) for content, mime in getattr(message, 'alternatives', []) if mime == 'text/html')
        lines = [
            '',
            '┌─────────────────── 메일 (개발용 출력, 실제로 보내지 않음) ───────────────────',
            f'│ 보낸 사람 : {message.from_email}',
            f'│ 받는 사람 : {", ".join(message.to)}',
            f'│ 제목      : {message.subject}',
            '├──────────────────────────────────────────────────────────────────────────────',
            *[f'│ {line}' for line in message.body.splitlines()],
            '├──────────────────────────────────────────────────────────────────────────────',
            f'│ (HTML 본문 함께 포함: {html_length}자)' if html_length else '│ (텍스트 본문만 있음)',
            '└──────────────────────────────────────────────────────────────────────────────',
            '',
        ]
        self.stream.write('\n'.join(lines) + '\n')
