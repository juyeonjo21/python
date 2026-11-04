"""
ERP 문의 관리 시스템 - Django 설정 파일

비밀번호·비밀키 같은 민감한 값은 이 파일에 직접 쓰지 않고
프로젝트 최상위의 .env 파일에서 읽어옵니다. (django-environ 사용)
"""

from pathlib import Path

import environ

# 프로젝트 최상위 폴더 (manage.py가 있는 위치)
BASE_DIR = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------
# .env 읽기
# ------------------------------------------------------------
# env('키', default=기본값) 형태로 .env의 값을 꺼내 씁니다.
env = environ.Env(
    DEBUG=(bool, False),  # .env에 DEBUG가 없으면 False(운영 모드)로 동작
)
environ.Env.read_env(BASE_DIR / '.env')

# 보안 키: 반드시 .env에 있어야 합니다. 없으면 서버가 켜지지 않습니다.
SECRET_KEY = env('SECRET_KEY')

# 개발 중에는 True, 운영 서버에서는 반드시 False
DEBUG = env('DEBUG')

# 접속을 허용할 도메인 목록 (쉼표로 구분)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])


# ------------------------------------------------------------
# 앱 등록
# ------------------------------------------------------------
INSTALLED_APPS = [
    # Django 기본 앱
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',  # "3시간 전" 같은 표시 (naturaltime)

    # 우리 프로젝트 앱
    'accounts',       # 사용자·부서·권한
    'inquiries',      # 문의·답변·이력·첨부 (핵심)
    'notices',        # 공지사항
    'notifications',  # 이메일 발송·발송 기록
    'dashboard',      # 통계
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',  # 한국어 등 언어 처리
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # 로그인하지 않은 사용자는 모든 페이지에서 로그인 화면으로 보냄
    # (로그인 화면처럼 예외가 필요한 곳은 login_not_required로 표시)
    'django.contrib.auth.middleware.LoginRequiredMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # 공통 템플릿 폴더 (base.html, components/ 등)
        'DIRS': [BASE_DIR / 'templates'],
        # 각 앱 안의 templates/ 폴더도 함께 찾음
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # 안 읽은 웹 알림 개수 (벨 배지·탭 제목)
                'notifications.context_processors.unread_notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# ------------------------------------------------------------
# 데이터베이스
# ------------------------------------------------------------
# .env의 DATABASE_URL 값으로 DB를 정합니다.
# 개발: sqlite:///db.sqlite3
# 운영: postgres://사용자:비밀번호@호스트:5432/DB이름  (나중에 전환)
DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}'),
}


# ------------------------------------------------------------
# 사용자 모델
# ------------------------------------------------------------
# Django 기본 User 대신 accounts 앱의 User(이름·부서·역할 추가)를 사용
AUTH_USER_MODEL = 'accounts.User'

# 로그인 화면 주소, 로그인 성공 후 기본 이동 주소
# (?next=로 원래 가려던 주소가 있으면 그곳으로 돌아감)
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard:home'


# ------------------------------------------------------------
# 비밀번호 규칙
# ------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ------------------------------------------------------------
# 언어·시간대
# ------------------------------------------------------------
LANGUAGE_CODE = 'ko-kr'    # 관리자 화면 등을 한국어로 표시
TIME_ZONE = 'Asia/Seoul'   # 서울 시간 기준
USE_I18N = True
USE_TZ = True              # DB에는 UTC로 저장하고, 화면에는 서울 시간으로 보여줌


# ------------------------------------------------------------
# 정적 파일 (CSS·JS·이미지)
# ------------------------------------------------------------
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']   # 개발 중 우리가 넣는 파일 위치
STATIC_ROOT = BASE_DIR / 'staticfiles'     # 운영 배포 시 collectstatic이 모아두는 위치


# ------------------------------------------------------------
# 업로드 파일 (첨부파일 등)
# ------------------------------------------------------------
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ------------------------------------------------------------
# 이메일 (값은 모두 .env에서 읽음 - 비밀번호를 코드에 쓰지 않음)
# ------------------------------------------------------------
# 개발: 터미널에 메일 내용을 출력하는 콘솔 백엔드
# 운영: django.core.mail.backends.smtp.EmailBackend 로 바꾸고 EMAIL_HOST 등을 채움
EMAIL_BACKEND = env('EMAIL_BACKEND', default='notifications.backends.ReadableConsoleEmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='localhost')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL', default=False)
EMAIL_TIMEOUT = env.int('EMAIL_TIMEOUT', default=10)  # 메일 서버가 응답하지 않을 때 기다리는 최대 시간(초)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='ERP Helpdesk <no-reply@example.com>')

# 개발용: 값이 있으면 모든 알림 메일을 이 주소 한 곳으로만 보냄 (제목 앞에 [원래 수신: 주소])
# 운영에서는 반드시 비워 둘 것
EMAIL_REDIRECT_TO = env('EMAIL_REDIRECT_TO', default='').strip()

# 메일 속 '문의 확인하기' 링크의 앞부분 (예: http://127.0.0.1:8001)
SITE_URL = env('SITE_URL', default='http://127.0.0.1:8001').rstrip('/')


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
