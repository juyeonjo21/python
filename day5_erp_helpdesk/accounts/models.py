"""
accounts 앱 모델 - 부서(Department)와 사용자(User)

※ 데이터는 삭제하지 않고 is_active=False로 비활성화합니다.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class Department(models.Model):
    """부서 (예: EMC, 품질, 회계)"""

    name = models.CharField('부서명', max_length=50, unique=True)
    is_active = models.BooleanField('사용 여부', default=True)

    class Meta:
        verbose_name = '부서'
        verbose_name_plural = '부서'
        ordering = ['name']

    def __str__(self):
        return self.name


class Job(models.TextChoices):
    """
    ERP 담당 직무 - 문의는 사람이 아니라 직무(팀)에 배정합니다.
    (문의 관리·처리 권한은 경영지원실에만 있고, 그 안에서 직무로 나눔)
    """

    BACKEND = 'BACKEND', '백엔드'
    FRONTEND = 'FRONTEND', '프론트'
    PLANNING = 'PLANNING', '기획'


class User(AbstractUser):
    """
    사용자 - Django 기본 User(아이디·비밀번호·로그인 기능)를 그대로 물려받고
    이름, 부서, 역할을 추가한 커스텀 User입니다.
    (is_active, email, username 등은 부모 클래스에 이미 있습니다.)
    """

    class Role(models.TextChoices):
        USER = 'USER', '일반 사용자'
        AGENT = 'AGENT', 'ERP 담당자'
        ADMIN = 'ADMIN', '관리자'

    name = models.CharField('이름', max_length=50)
    email = models.EmailField('이메일', blank=True)
    department = models.ForeignKey(
        Department,
        verbose_name='부서',
        on_delete=models.PROTECT,  # 사용자가 있는 부서는 삭제 불가
        null=True,
        blank=True,
        related_name='users',
    )
    role = models.CharField('역할', max_length=10, choices=Role.choices, default=Role.USER)
    # 담당자·관리자의 직무 (일반 사용자는 비워 둠)
    job = models.CharField('직무', max_length=10, choices=Job.choices, blank=True)

    class Meta:
        verbose_name = '사용자'
        verbose_name_plural = '사용자'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.username})' if self.name else self.username

    # 화면·권한 검사에서 쓰기 편하도록 만든 역할 확인용 속성
    # (createsuperuser로 만든 최고 관리자는 역할과 관계없이 관리자로 취급)
    @property
    def is_agent(self):
        return self.role == self.Role.AGENT

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_staff_member(self):
        """담당자 또는 관리자 = 전체 문의를 볼 수 있는 사람"""
        return self.role == self.Role.AGENT or self.is_admin_role

    @property
    def role_label(self):
        """화면에 보여줄 역할 이름"""
        return self.Role.ADMIN.label if self.is_admin_role else self.get_role_display()
