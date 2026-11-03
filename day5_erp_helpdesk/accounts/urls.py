"""accounts 앱 URL - 로그인·로그아웃 (Django 기본 인증 화면을 우리 디자인으로 사용)"""

from django.contrib.auth import views as auth_views
from django.urls import path

app_name = 'accounts'

urlpatterns = [
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='accounts/login.html',
            redirect_authenticated_user=True,  # 이미 로그인했다면 홈으로
        ),
        name='login',
    ),
    # 로그아웃은 보안상 POST 요청으로만 처리됨 (사이드바의 로그아웃 버튼이 form으로 전송)
    path(
        'logout/',
        auth_views.LogoutView.as_view(template_name='accounts/logged_out.html'),
        name='logout',
    ),
]
