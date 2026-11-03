from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.stats, name='stats'),
    path('stats/', RedirectView.as_view(pattern_name='dashboard:stats', query_string=True)),  # 예전 주소
    path('manage/', views.manage, name='manage'),
    path('ui-kit/', views.ui_kit, name='ui_kit'),
]
