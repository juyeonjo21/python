"""
오래된 웹 알림 정리

사용법:
    python manage.py cleanup_notifications              # 읽은 지 90일 지난 알림 삭제
    python manage.py cleanup_notifications --days 30    # 기간 변경
    python manage.py cleanup_notifications --dry-run    # 지우지 않고 몇 건인지만 확인

※ 읽은 알림만 지웁니다 (안 읽은 알림은 오래돼도 남김).
※ 알림은 업무 이력이 아니므로 지워도 됩니다. 업무 이력은 inquiries.History에 그대로 남습니다.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from notifications.models import Notification


class Command(BaseCommand):
    help = '읽은 지 오래된 웹 알림을 삭제합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90, help='읽은 지 며칠 지난 알림을 지울지 (기본 90일)')
        parser.add_argument('--dry-run', action='store_true', help='실제로 지우지 않고 대상 개수만 출력')

    def handle(self, *args, **options):
        days = options['days']
        if days < 1:
            raise CommandError('--days는 1 이상이어야 합니다.')

        cutoff = timezone.now() - timedelta(days=days)
        targets = Notification.objects.filter(is_read=True, read_at__lt=cutoff)
        count = targets.count()
        cutoff_text = timezone.localtime(cutoff).strftime('%Y-%m-%d %H:%M')

        if options['dry_run']:
            self.stdout.write(f'[미리보기] {cutoff_text} 이전에 읽은 알림 {count}건이 삭제 대상입니다. (지우지 않음)')
            return

        targets.delete()
        self.stdout.write(self.style.SUCCESS(f'{cutoff_text} 이전에 읽은 알림 {count}건을 삭제했습니다.'))
