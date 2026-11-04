"""
inquiries 앱 업무 처리 함수

화면(view)은 입력을 받고 결과를 보여주는 일만 하고,
'문의 등록', '상태 변경'처럼 여러 테이블을 함께 바꾸는 업무 처리는 이 파일에 모아 둡니다.
- 모든 변경은 History에 기록됩니다.
- 메일 알림은 DB 저장이 확정된 뒤(transaction.on_commit) notifications.services의 함수를 부릅니다.
  robust=True: 알림에서 오류가 나도 이미 저장된 업무 처리(화면 요청)는 성공으로 끝남
- notify=False: 다른 처리 안에서 따라 바뀌는 경우(예: 답변 등록 → 답변 완료) 메일을 따로 보내지 않음
- 입력이 업무 규칙에 맞지 않으면 ValidationError를 냅니다. (화면에서 받아 오류로 표시)
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import Job
from notifications.services import (
    notify_assigned,
    notify_comment_added,
    notify_inquiry_created,
    notify_status_changed,
)

from .models import Attachment, Category, Comment, History, Inquiry

S = Inquiry.Status

# 답변을 달면 자동으로 '답변 완료'가 되는 상태들
AUTO_ANSWER_FROM = (S.RECEIVED, S.CHECKING, S.IN_PROGRESS)


def _log(inquiry, actor, action, from_value='', to_value='', memo=''):
    """처리 이력 1건 기록"""
    History.objects.create(
        inquiry=inquiry, actor=actor, action=action,
        from_value=str(from_value or ''), to_value=str(to_value or ''), memo=memo,
    )


def _save_attachments(inquiry, files, uploaded_by, comment=None):
    for f in files:
        Attachment.objects.create(
            inquiry=inquiry, comment=comment, file=f,
            original_name=f.name, size=f.size, uploaded_by=uploaded_by,
        )


def _job_label(job):
    return Job(job).label if job else ''


# ------------------------------------------------------------
# 문의 등록
# ------------------------------------------------------------
def create_inquiry(*, requester, category, title, content, priority=Inquiry.Priority.NORMAL,
                   extra_data=None, files=()):
    """
    문의를 등록한다.
      1) 문의 저장 (문의번호 자동 부여, 요청 부서 = 요청자의 현재 부서)
      2) 첨부파일 저장
      3) 처리 이력(History)에 '등록' 기록
      4) 모두 성공하면 알림 메일 발송 (지금은 자리만 있음)
    1~3 중 하나라도 실패하면 전부 취소됩니다. (transaction.atomic)
    """
    with transaction.atomic():
        inquiry = Inquiry.objects.create(
            requester=requester,
            department=requester.department,
            category=category,
            title=title,
            content=content,
            priority=priority,
            extra_data=extra_data or {},
        )
        _save_attachments(inquiry, files, requester)
        _log(inquiry, requester, History.Action.CREATE, to_value=S.RECEIVED.label)

        # DB 저장이 확정된 뒤에만 메일 발송 (저장이 취소되면 메일도 안 나감)
        transaction.on_commit(lambda: notify_inquiry_created(inquiry), robust=True)

    return inquiry


# ------------------------------------------------------------
# 상태 변경
# ------------------------------------------------------------
def change_status(inquiry, actor, new_status, reason='', notify=True):
    """
    상태를 바꾼다. 바뀌지 않았으면 아무것도 하지 않고 False를 돌려준다.
    - 보류·반려: 사유(reason) 필수 → resolution과 이력 메모에 저장
    - 처리 완료: 처리 결과 필수 (이미 적힌 처리 결과가 있으면 생략 가능)
    - 답변 완료가 되면 resolved_at, 처리 완료가 되면 closed_at 자동 기록 (Inquiry.save)
    - 처리 완료를 다시 열면 closed_at을 비움
    """
    if new_status not in S.values:
        raise ValidationError('알 수 없는 상태입니다.')
    old_status = inquiry.status
    if new_status == old_status:
        return False

    reason = (reason or '').strip()
    if new_status in Inquiry.REASON_REQUIRED_STATUSES and not reason:
        raise ValidationError(f'{S(new_status).label} 사유를 입력해 주세요.')
    # 처리 완료: 처리 결과 필수 (보류·반려 사유는 처리 결과로 치지 않음)
    leaving_hold = old_status in Inquiry.REASON_REQUIRED_STATUSES
    if new_status == S.CLOSED and not (reason or (inquiry.resolution.strip() and not leaving_hold)):
        raise ValidationError('처리 결과를 입력해 주세요.')

    with transaction.atomic():
        inquiry.status = new_status
        if reason:
            inquiry.resolution = reason
        elif leaving_hold:
            inquiry.resolution = ''  # 보류·반려가 풀리면 사유는 지움 (사유는 이력 메모에 남아 있음)
        if old_status == S.CLOSED:
            inquiry.closed_at = None
        inquiry.save()
        _log(inquiry, actor, History.Action.STATUS, S(old_status).label, S(new_status).label, memo=reason)
        if notify:
            transaction.on_commit(
                lambda: notify_status_changed(inquiry, old_status, new_status, actor), robust=True)
    return True


# ------------------------------------------------------------
# 담당 직무 지정
# ------------------------------------------------------------
def assign(inquiry, actor, job, notify=True):
    """
    담당 직무(백엔드/프론트/기획)를 바꾼다. (job='' 이면 미지정으로)
    직무를 지정했을 때 상태가 '접수'면 자동으로 '확인 중'으로 바꾼다.
    """
    job = job or ''
    if job and job not in Job.values:
        raise ValidationError('알 수 없는 직무입니다.')
    old = inquiry.assigned_job
    if old == job:
        return False

    with transaction.atomic():
        inquiry.assigned_job = job
        inquiry.save()
        _log(inquiry, actor, History.Action.ASSIGN, _job_label(old), _job_label(job))
        if job and inquiry.status == S.RECEIVED:
            change_status(inquiry, actor, S.CHECKING, notify=False)  # 자동 변경은 상태 메일 없음
        if job and notify:
            transaction.on_commit(lambda: notify_assigned(inquiry, job, actor), robust=True)
    return True


# ------------------------------------------------------------
# 카테고리·우선순위 변경
# ------------------------------------------------------------
def change_category(inquiry, actor, category):
    if not isinstance(category, Category) or not category.is_active:
        raise ValidationError('사용할 수 없는 카테고리입니다.')
    old = inquiry.category
    if old == category:
        return False
    with transaction.atomic():
        inquiry.category = category
        inquiry.save()
        _log(inquiry, actor, History.Action.CATEGORY, old.name, category.name)
    return True


def change_priority(inquiry, actor, priority):
    if priority not in Inquiry.Priority.values:
        raise ValidationError('알 수 없는 우선순위입니다.')
    old = inquiry.priority
    if old == priority:
        return False
    with transaction.atomic():
        inquiry.priority = priority
        inquiry.save()
        _log(inquiry, actor, History.Action.PRIORITY,
             Inquiry.Priority(old).label, Inquiry.Priority(priority).label)
    return True


# ------------------------------------------------------------
# 답변·코멘트 등록
# ------------------------------------------------------------
def allowed_comment_types(user):
    """작성자 역할별로 쓸 수 있는 글 종류"""
    if user.is_staff_member:
        return [Comment.Type.ANSWER, Comment.Type.INTERNAL]
    return [Comment.Type.USER]


def add_comment(inquiry, author, comment_type, content, files=()):
    """
    답변·내부 메모·사용자 코멘트를 등록한다.
    담당자가 '답변'을 달면:
      - 담당 직무가 비어 있으면 답변한 사람의 직무로 지정
      - 상태가 접수·확인 중·처리 중이면 '답변 완료'로 변경
    """
    content = (content or '').strip()
    if not content:
        raise ValidationError('내용을 입력해 주세요.')
    if comment_type not in allowed_comment_types(author):
        raise ValidationError('이 종류의 글을 작성할 권한이 없습니다.')

    with transaction.atomic():
        comment = Comment.objects.create(inquiry=inquiry, author=author, type=comment_type, content=content)
        _save_attachments(inquiry, files, author, comment=comment)
        _log(inquiry, author, History.Action.COMMENT, to_value=comment.get_type_display())

        if comment_type == Comment.Type.ANSWER:
            if not inquiry.assigned_job and author.job:
                assign(inquiry, author, author.job, notify=False)  # 답변 메일 1통만 보내기 위해
            if inquiry.status in AUTO_ANSWER_FROM:
                change_status(inquiry, author, S.ANSWERED, notify=False)

        inquiry.save(update_fields=['updated_at'])  # 목록의 '최근 업데이트' 갱신
        if comment_type != Comment.Type.INTERNAL:
            transaction.on_commit(lambda: notify_comment_added(comment), robust=True)
    return comment
