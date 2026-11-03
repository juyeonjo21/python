"""inquiries 앱 관리자(Admin) 화면 설정"""

from django.contrib import admin

from accounts.admin import SoftDeleteAdminMixin

from .models import Attachment, Category, Comment, History, Inquiry, RelatedInquiry


@admin.register(Category)
class CategoryAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'parent', 'sort_order', 'is_active']
    list_editable = ['sort_order']  # 목록에서 바로 순서 수정
    list_filter = ['is_active', 'parent']
    search_fields = ['name']


# ------------------------------------------------------------
# 문의 상세 화면 안에 함께 보여줄 하위 목록(inline)
# ------------------------------------------------------------
class CommentInline(admin.StackedInline):
    model = Comment
    extra = 0
    fields = ['type', 'author', 'content', 'created_at']
    readonly_fields = ['created_at']


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    fields = ['file', 'original_name', 'size', 'comment', 'uploaded_by', 'created_at']
    readonly_fields = ['size', 'created_at']


class RelatedInquiryInline(admin.TabularInline):
    model = RelatedInquiry
    fk_name = 'inquiry'
    extra = 0
    autocomplete_fields = ['related']


class HistoryInline(admin.TabularInline):
    """이력은 보기만 가능"""

    model = History
    extra = 0
    fields = ['created_at', 'actor', 'action', 'from_value', 'to_value', 'memo']
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = [
        'inquiry_no', 'title', 'category', 'requester', 'department',
        'assigned_job', 'status', 'priority', 'created_at',
    ]
    list_display_links = ['inquiry_no', 'title']
    list_filter = ['status', 'priority', 'category', 'department', 'assigned_job', 'created_at']
    search_fields = ['inquiry_no', 'title', 'content', 'requester__name', 'requester__username']
    date_hierarchy = 'created_at'  # 상단에 연·월·일 이동 메뉴
    autocomplete_fields = ['requester']
    list_select_related = ['category', 'requester', 'department']
    readonly_fields = ['inquiry_no', 'created_at', 'updated_at']
    fieldsets = (
        ('문의 내용', {'fields': ('inquiry_no', 'title', 'content', 'category', 'extra_data')}),
        ('요청 정보', {'fields': ('requester', 'department')}),
        ('처리 정보', {'fields': ('assigned_job', 'status', 'priority', 'resolution')}),
        ('일시', {'fields': ('created_at', 'updated_at', 'resolved_at', 'closed_at')}),
    )
    inlines = [CommentInline, AttachmentInline, RelatedInquiryInline, HistoryInline]

    # 문의는 삭제하지 않음 (이력 보존)
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['inquiry', 'type', 'author', 'short_content', 'created_at']
    list_filter = ['type', 'created_at']
    search_fields = ['inquiry__inquiry_no', 'content', 'author__name']
    autocomplete_fields = ['inquiry', 'author']
    list_select_related = ['inquiry', 'author']

    @admin.display(description='내용')
    def short_content(self, obj):
        return obj.content[:40] + ('…' if len(obj.content) > 40 else '')


@admin.register(History)
class HistoryAdmin(admin.ModelAdmin):
    """이력: 목록·상세 보기만 가능 (추가·수정·삭제 불가)"""

    list_display = ['created_at', 'inquiry', 'actor', 'action', 'from_value', 'to_value']
    list_filter = ['action', 'created_at']
    search_fields = ['inquiry__inquiry_no', 'actor__name', 'memo']
    list_select_related = ['inquiry', 'actor']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ['original_name', 'inquiry', 'size', 'uploaded_by', 'created_at']
    list_filter = ['created_at']
    search_fields = ['original_name', 'inquiry__inquiry_no']
    autocomplete_fields = ['inquiry', 'uploaded_by']
    readonly_fields = ['size']


@admin.register(RelatedInquiry)
class RelatedInquiryAdmin(admin.ModelAdmin):
    list_display = ['inquiry', 'related', 'note']
    search_fields = ['inquiry__inquiry_no', 'related__inquiry_no', 'note']
    autocomplete_fields = ['inquiry', 'related']
