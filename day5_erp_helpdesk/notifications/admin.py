"""notifications 앱 관리자(Admin) 화면 설정"""

from django.contrib import admin

from .models import EmailLog, Notification


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'to', 'subject', 'event_type', 'status', 'retry_count', 'sent_at']
    list_filter = ['status', 'event_type', 'created_at']
    search_fields = ['to', 'subject', 'inquiry__inquiry_no']
    autocomplete_fields = ['inquiry']
    readonly_fields = ['created_at']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """웹 알림 - 보기 전용 (알림은 업무 처리 중에만 자동으로 만들어짐). 정리를 위한 삭제만 허용"""

    list_display = ['created_at', 'recipient', 'event_type', 'message', 'is_read', 'read_at']
    list_filter = ['is_read', 'event_type', 'created_at']
    search_fields = ['message', 'recipient__name', 'recipient__username', 'inquiry__inquiry_no']
    list_select_related = ['recipient']
    readonly_fields = [f.name for f in Notification._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
