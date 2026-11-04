"""
알림 정책 - '어떤 상황에 누구에게, 어떤 채널(웹/이메일)로 보낼지'를 이 파일 한 곳에서 정합니다.
정책을 바꾸려면 이 파일만 고치면 됩니다.
  - 실제 웹 알림 만들기: inapp.py / 이메일 발송: email.py / 호출 순서: services.py

| 상황                 | 받는 사람                              | 웹 | 이메일                       |
|----------------------|----------------------------------------|----|------------------------------|
| 문의 등록            | 활성 담당자 전원                       | O  | 우선순위가 긴급(URGENT)일 때만 |
| 문의 등록(접수 확인) | 요청자                                 | X  | X (템플릿은 남겨 둠, 켜기 가능) |
| 직무 지정            | 해당 직무 담당자                       | O  | X                            |
| 답변 등록            | 요청자                                 | O  | O                            |
| 사용자 코멘트        | 배정 직무 담당자 (미배정이면 전원)     | O  | X                            |
| 상태 변경            | 요청자                                 | O  | 처리 완료·보류·반려만        |
| 내부 메모            | 없음                                   | X  | X                            |

공통 규칙 (_finalize, 두 채널 모두):
- 그 행동을 한 본인(actor)에게는 보내지 않는다
- 받는 사람이 겹치면 1번만
- 비활성 계정 제외
채널별 차이:
- 웹 알림은 이메일 주소가 없어도 받는다
- 문의 등록 메일은 이메일 주소가 있는 담당자에게만 보낸다
"""

from django.db.models import Q

from accounts.models import User
from inquiries.models import Comment, Inquiry

S = Inquiry.Status

# 요청자에게 상태 변경 메일을 보내는 상태
STATUS_CHANGE_EMAIL = {S.CLOSED, S.ON_HOLD, S.REJECTED}

# ------------------------------------------------------------
# 채널 표: True(항상) / False(안 보냄) / 함수(조건이 맞을 때만)
#   함수는 상황 정보를 키워드로 받음 (inquiry, new_status 등)
# ------------------------------------------------------------
CHANNELS = {
    'CREATED_STAFF':     {'web': True,  'email': lambda inquiry, **_: inquiry.priority == Inquiry.Priority.URGENT},
    'CREATED_REQUESTER': {'web': False, 'email': False},  # 접수 확인 메일 - 다시 켜려면 email을 True로
    'ASSIGNED':          {'web': True,  'email': False},
    'ANSWERED':          {'web': True,  'email': True},
    'COMMENTED':         {'web': True,  'email': False},
    'STATUS_CHANGED':    {'web': True,  'email': lambda new_status, **_: new_status in STATUS_CHANGE_EMAIL},
    'INTERNAL':          {'web': False, 'email': False},
}


def channel_on(situation, channel, **context):
    """CHANNELS 표에서 이 상황·채널이 켜져 있는지 (조건 함수면 상황 정보로 판단)"""
    rule = CHANNELS.get(situation, {}).get(channel, False)
    return bool(rule(**context)) if callable(rule) else bool(rule)


# ------------------------------------------------------------
# 받는 사람 후보
# ------------------------------------------------------------
def active_staff():
    """활성 담당자·관리자 (최고 관리자 포함)"""
    return User.objects.filter(
        Q(role__in=[User.Role.AGENT, User.Role.ADMIN]) | Q(is_superuser=True), is_active=True
    ).order_by('pk')


def job_staff(job):
    """해당 직무를 가진 활성 담당자"""
    return active_staff().filter(job=job)


def _finalize(users, actor=None, exclude=()):
    """본인(actor)·제외 대상 빼기 + 중복 제거 + 비활성 제외 (순서는 유지)"""
    skip = {u.pk for u in exclude if u}
    if actor:
        skip.add(actor.pk)
    result, seen = [], set()
    for user in users:
        if user and user.is_active and user.pk not in skip and user.pk not in seen:
            seen.add(user.pk)
            result.append(user)
    return result


# ------------------------------------------------------------
# 상황별 받는 사람 (channel: 'web' 또는 'email')
# ------------------------------------------------------------
def created_staff_recipients(inquiry, channel):
    """
    문의 등록 → 활성 담당자 전원 (요청자 본인은 제외)
    메일은 이메일 주소가 있는 사람만, 웹 알림은 주소가 없어도 받음
    """
    staff = active_staff()
    if channel == 'email':
        staff = staff.exclude(email='')
    return _finalize(staff, actor=inquiry.requester)


def created_requester_recipients(inquiry):
    """문의 등록(접수 확인) → 요청자 본인 ('본인 제외'의 예외. 지금은 CHANNELS에서 꺼져 있음)"""
    return _finalize([inquiry.requester])


def assigned_recipients(inquiry, job, actor):
    """직무 지정 → 그 직무 담당자 전원 (지정한 본인 제외)"""
    if not job:
        return []
    return _finalize(job_staff(job), actor=actor)


def answered_recipients(comment):
    """답변 등록 → 요청자"""
    return _finalize([comment.inquiry.requester], actor=comment.author)


def commented_recipients(comment):
    """사용자 코멘트 → 배정된 직무 담당자, 미배정이면 활성 담당자 전원"""
    inquiry = comment.inquiry
    candidates = job_staff(inquiry.assigned_job) if inquiry.assigned_job else active_staff()
    return _finalize(candidates, actor=comment.author)


def status_changed_recipients(inquiry, actor):
    """상태 변경 → 요청자 (어떤 상태를 메일로 보낼지는 CHANNELS의 STATUS_CHANGED에서 정함)"""
    return _finalize([inquiry.requester], actor=actor)


def comment_situation(comment):
    """글 종류 → CHANNELS 표의 상황 이름"""
    return {
        Comment.Type.ANSWER: 'ANSWERED',
        Comment.Type.USER: 'COMMENTED',
    }.get(comment.type, 'INTERNAL')


def comment_recipients(comment):
    """글 종류에 맞는 받는 사람 (내부 메모는 아무에게도 보내지 않음)"""
    if comment.type == Comment.Type.ANSWER:
        return answered_recipients(comment)
    if comment.type == Comment.Type.USER:
        return commented_recipients(comment)
    return []
