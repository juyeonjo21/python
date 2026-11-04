from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    # 웹 알림
    path('notifications/', views.notification_list, name='list'),
    path('notifications/badge/', views.badge, name='badge'),          # HTMX: 안 읽은 개수 배지
    path('notifications/panel/', views.panel, name='panel'),          # HTMX: 벨 패널
    path('notifications/read-all/', views.read_all, name='read_all'),  # 모두 읽음 (POST)
    path('notifications/<int:pk>/go/', views.go, name='go'),           # 알림 클릭 → 문의 상세
    # 메일 발송 기록 (관리자)
    path('manage/email-logs/', views.email_log_list, name='email_logs'),
]
