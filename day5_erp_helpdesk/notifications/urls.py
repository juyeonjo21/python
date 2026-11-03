from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('manage/email-logs/', views.email_log_list, name='email_logs'),
]
