"""accounts 앱 관리자(Admin) 화면 설정"""

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Department, User


# ------------------------------------------------------------
# 공통: 삭제 대신 활성/비활성으로 관리하기 위한 기능
# ------------------------------------------------------------
@admin.action(description='선택 항목 비활성화')
def make_inactive(modeladmin, request, queryset):
    count = queryset.update(is_active=False)
    modeladmin.message_user(request, f'{count}건을 비활성화했습니다.', messages.SUCCESS)


@admin.action(description='선택 항목 활성화')
def make_active(modeladmin, request, queryset):
    count = queryset.update(is_active=True)
    modeladmin.message_user(request, f'{count}건을 활성화했습니다.', messages.SUCCESS)


class SoftDeleteAdminMixin:
    """삭제 버튼을 없애고 활성/비활성 기능을 넣어주는 공통 설정"""

    actions = [make_inactive, make_active]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Department)
class DepartmentAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'user_count', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name']

    @admin.display(description='소속 인원')
    def user_count(self, obj):
        return obj.users.filter(is_active=True).count()


@admin.register(User)
class UserAdmin(SoftDeleteAdminMixin, BaseUserAdmin):
    list_display = ['username', 'name', 'email', 'department', 'role', 'job', 'is_active', 'last_login']
    list_filter = ['role', 'job', 'department', 'is_active', 'is_staff']
    search_fields = ['username', 'name', 'email']
    ordering = ['name']

    # 사용자 수정 화면에 보여줄 항목 묶음
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('기본 정보', {'fields': ('name', 'email', 'department', 'role', 'job')}),
        ('권한', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('기록', {'fields': ('last_login', 'date_joined')}),
    )
    # 사용자 추가 화면에 보여줄 항목
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'name', 'email', 'department', 'role', 'job'),
        }),
    )
