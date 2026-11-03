"""notices 앱 폼"""

from django import forms

from inquiries.models import Category

from .models import Notice


class NoticeForm(forms.ModelForm):
    """공지 작성·수정 (작성자는 view에서 로그인 사용자로 채움)"""

    class Meta:
        model = Notice
        fields = ['title', 'category', 'inquiry_category', 'is_pinned', 'content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 14}),
        }
        help_texts = {
            'inquiry_category': '선택하면 해당 카테고리로 문의를 등록할 때 참고 공지로 표시됩니다.',
            'is_pinned': '목록 맨 위와 홈 화면에 표시됩니다.',
        }
        error_messages = {
            'title': {'required': '제목을 입력해 주세요.'},
            'content': {'required': '내용을 입력해 주세요.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].choices = [('', '분류 없음')] + list(Notice.Category.choices)
        self.fields['inquiry_category'].queryset = Category.objects.filter(is_active=True)
        self.fields['inquiry_category'].empty_label = '연결 안 함'
        self.fields['title'].widget.attrs['placeholder'] = '공지 제목'
        self.fields['content'].widget.attrs['placeholder'] = '공지 내용을 입력하세요. 줄바꿈은 그대로 표시됩니다.'
        # 공통 디자인 클래스 (체크박스 제외)
        for name, field in self.fields.items():
            if name == 'is_pinned':
                field.widget.attrs['class'] = 'w-4 h-4 rounded border-line text-accent focus:ring-accent/30'
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs['class'] = 'input h-auto py-2.5 leading-relaxed'
            else:
                field.widget.attrs['class'] = 'input'
