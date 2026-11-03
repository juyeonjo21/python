"""
샘플 담당자 계정(agent1~3)에 직무를 채워 넣는 데이터 마이그레이션

문의 담당을 '사람'에서 '직무'로 바꾸면서, 기존 문의의 담당자 정보를
그 사람의 직무로 옮기려면 직무가 먼저 있어야 합니다. (inquiries 0003에서 사용)
※ 샘플 계정에만 해당하며, 직무가 이미 있으면 건드리지 않습니다.
"""

from django.db import migrations

SAMPLE_JOBS = {'agent1': 'BACKEND', 'agent2': 'FRONTEND', 'agent3': 'PLANNING'}


def fill_jobs(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    for username, job in SAMPLE_JOBS.items():
        User.objects.filter(username=username, role='AGENT', job='').update(job=job)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_user_job'),
    ]

    operations = [
        migrations.RunPython(fill_jobs, migrations.RunPython.noop),
    ]
