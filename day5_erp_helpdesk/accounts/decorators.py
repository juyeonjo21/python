"""
역할(권한) 검사용 데코레이터

사용 예:
    @agent_required          # 담당자·관리자만
    def inquiry_list(request): ...

    @admin_required          # 관리자만
    def ui_kit(request): ...

권한이 없으면 403(접근 권한 없음) 화면을 보여줍니다.
로그인 여부는 LoginRequiredMiddleware가 먼저 검사합니다.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied


def _check(test):
    """test(user)가 True일 때만 view를 실행하는 데코레이터를 만든다."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not test(request.user):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


agent_required = _check(lambda user: user.is_staff_member)
admin_required = _check(lambda user: user.is_admin_role)
