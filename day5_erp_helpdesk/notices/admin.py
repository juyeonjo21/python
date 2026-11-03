"""notices 앱 관리자(Admin) 화면 설정"""

from django.contrib import admin

from .models import Notice


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'inquiry_category', 'is_pinned', 'author', 'created_at']
    list_editable = ['is_pinned']  # 목록에서 바로 고정 여부 변경
    list_filter = ['category', 'inquiry_category', 'is_pinned', 'created_at']
    search_fields = ['title', 'content']
    autocomplete_fields = ['author']
