"""
최상위 URL 설정 - 주소(URL)와 처리할 화면을 연결합니다.
각 앱의 세부 주소는 앱 폴더의 urls.py에 있습니다.

※ 업로드 파일(media)은 주소로 바로 열지 않습니다.
   권한을 검사하는 다운로드 주소(/inquiries/attachments/<번호>/)로만 받을 수 있습니다.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),                  # Django 관리자 페이지
    path('accounts/', include('accounts.urls')),      # 로그인·로그아웃
    path('inquiries/', include('inquiries.urls')),    # 문의
    path('notices/', include('notices.urls')),        # 공지사항
    path('', include('notifications.urls')),          # 메일 발송 기록 (/manage/email-logs/)
    path('', include('dashboard.urls')),              # 홈·통계·관리·UI 키트
]
