"""notifications 앱 관리자(Admin) 화면 설정"""

from django.contrib import admin

from .models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'to', 'subject', 'event_type', 'status', 'retry_count', 'sent_at']
    list_filter = ['status', 'event_type', 'created_at']
    search_fields = ['to', 'subject', 'inquiry__inquiry_no']
    autocomplete_fields = ['inquiry']
    readonly_fields = ['created_at']
