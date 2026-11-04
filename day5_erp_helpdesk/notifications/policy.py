"""
이메일 알림 정책 - '어떤 상황에 누구에게 보낼지'를 이 파일 한 곳에서 정합니다.
정책을 바꾸려면 이 파일만 고치면 됩니다. (실제 발송은 email.py, 호출은 services.py)

| 상황                     | 받는 사람                                                       |
|--------------------------|-----------------------------------------------------------------|
| 문의 등록                | 활성 담당자 전원(이메일 있는 사람) + 요청자(접수 확인 메일)     |
| 직무 지정                | 해당 직무를 가진 활성 담당자 전원                               |
| 답변(ANSWER) 등록        | 요청자                                                          |
| 사용자 코멘트(USER) 등록 | 배정된 직무 담당자 전원, 미배정이면 활성 담당자 전원             |
| 상태 변경                | 요청자 (처리 완료·보류·반려일 때만)                              |
| 내부 메모(INTERNAL)      | 보내지 않음                                                     |

공통 규칙 (_finalize):
- 그 행동을 한 본인(actor)에게는 보내지 않는다
- 받는 사람이 겹치면 1통만 보낸다
- 비활성 계정에는 보내지 않는다
"""

from django.db.models import Q

from accounts.models import User
from inquiries.models import Comment, Inquiry

S = Inquiry.Status

# 요청자에게 상태 변경 메일을 보내는 상태
STATUS_CHANGE_NOTIFY = {S.CLOSED, S.ON_HOLD, S.REJECTED}


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
# 상황별 받는 사람
# ------------------------------------------------------------
def created_recipients(inquiry):
    """
    문의 등록 → (담당자 목록, 요청자 목록)
    - 요청자에게는 '접수 확인' 메일 (표에 따라 행동한 본인이지만 예외로 보냄)
    - 요청자가 담당자이기도 하면 담당자용 메일은 빼고 접수 확인 1통만
    """
    requester = _finalize([inquiry.requester])
    staff = _finalize(active_staff().exclude(email=''), exclude=[inquiry.requester])
    return staff, requester


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


def status_changed_recipients(inquiry, new_status, actor):
    """상태 변경 → 요청자 (처리 완료·보류·반려일 때만)"""
    if new_status not in STATUS_CHANGE_NOTIFY:
        return []
    return _finalize([inquiry.requester], actor=actor)


def comment_recipients(comment):
    """글 종류에 맞는 받는 사람 (내부 메모는 아무에게도 보내지 않음)"""
    if comment.type == Comment.Type.ANSWER:
        return answered_recipients(comment)
    if comment.type == Comment.Type.USER:
        return commented_recipients(comment)
    return []
