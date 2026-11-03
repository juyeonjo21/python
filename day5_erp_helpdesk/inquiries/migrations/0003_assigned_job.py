"""
문의 담당을 '사람(assignee)'에서 '직무(assigned_job)'로 변경

1) assigned_job 칸 추가
2) 기존 담당자가 있으면 그 사람의 직무를 옮겨 적음 (직무가 없는 사람이면 미지정)
3) assignee 칸 삭제
"""

from django.db import migrations, models


def copy_assignee_job(apps, schema_editor):
    Inquiry = apps.get_model('inquiries', 'Inquiry')
    for inquiry in Inquiry.objects.exclude(assignee=None).select_related('assignee'):
        if inquiry.assignee.job:
            Inquiry.objects.filter(pk=inquiry.pk).update(assigned_job=inquiry.assignee.job)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_seed_staff_jobs'),
        ('inquiries', '0002_alter_history_action'),
    ]

    operations = [
        migrations.AddField(
            model_name='inquiry',
            name='assigned_job',
            field=models.CharField(
                blank=True, choices=[('BACKEND', '백엔드'), ('FRONTEND', '프론트'), ('PLANNING', '기획')],
                db_index=True, max_length=10, verbose_name='담당 직무',
            ),
        ),
        migrations.RunPython(copy_assignee_job, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='inquiry',
            name='assignee',
        ),
    ]
