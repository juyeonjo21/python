from django.urls import path

from . import views

app_name = 'inquiries'

urlpatterns = [
    path('', views.inquiry_list, name='list'),
    path('new/', views.inquiry_create, name='create'),
    path('new/reference/', views.inquiry_reference, name='create_reference'),  # HTMX: 참고 패널
    path('mine/', views.my_inquiries, name='mine'),
    path('attachments/<int:pk>/', views.attachment_download, name='attachment_download'),
    path('attachments/<int:pk>/view/', views.attachment_view, name='attachment_view'),  # 이미지 바로 보기
    # 예: /inquiries/ERP-2026-0001/  (new/, mine/보다 아래에 두어야 함)
    path('<str:inquiry_no>/', views.inquiry_detail, name='detail'),
    path('<str:inquiry_no>/update/', views.inquiry_update, name='update'),      # HTMX: 속성 패널 저장
    path('<str:inquiry_no>/comments/', views.comment_create, name='comment'),   # HTMX: 답변·코멘트 등록
]
