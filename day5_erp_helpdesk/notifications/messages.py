"""
웹 알림에 보일 한 줄 문장 만들기

- 요청자에게 보이는 문장에는 담당자 개인 이름 대신 'ERP 담당자(직무)'를 씀 (메일과 같은 정책)
- 담당자끼리 보는 문장(새 문의, 직무 배정, 코멘트)에는 행동한 사람 이름을 씀
- 조사(으로/로)는 앞 글자의 받침에 맞춰 붙임
"""

from inquiries.models import Inquiry

MESSAGE_MAX = 255  # Notification.message 칸 길이


def staff_display(user):
    """요청자에게 보여줄 담당자 표시: 'ERP 담당자(백엔드)' / 직무가 없으면 'ERP 담당자'"""
    if user and user.job:
        return f'ERP 담당자({user.get_job_display()})'
    return 'ERP 담당자'


def person(user):
    """담당자끼리 보는 문장에서 쓰는 이름"""
    if not user:
        return '누군가'
    return user.name or user.username


def euro(word):
    """조사 '으로/로' 고르기: '처리 중' → '으로', '보류' → '로' (받침이 없거나 ㄹ 받침이면 '로')"""
    last = word.strip()[-1:] or ' '
    if '가' <= last <= '힣':
        final = (ord(last) - ord('가')) % 28  # 0 = 받침 없음, 8 = ㄹ
        return '로' if final in (0, 8) else '으로'
    return '로'


def _cut(text):
    return text if len(text) <= MESSAGE_MAX else text[:MESSAGE_MAX - 1] + '…'


# ------------------------------------------------------------
# 상황별 문장
# ------------------------------------------------------------
def created(inquiry):
    """새 문의 → 담당자에게"""
    return _cut(f'{person(inquiry.requester)}님이 {inquiry.inquiry_no} 문의를 등록했습니다')


def assigned(inquiry, job_label, actor):
    """직무 배정 → 그 직무 담당자에게"""
    return _cut(f'{person(actor)}님이 {inquiry.inquiry_no} 문의를 {job_label} 직무에 배정했습니다')


def answered(inquiry, actor):
    """답변 → 요청자에게 (담당자 이름 대신 직무)"""
    return _cut(f'{staff_display(actor)}가 {inquiry.inquiry_no}에 답변을 등록했습니다')


def commented(inquiry, actor):
    """사용자 코멘트 → 담당자에게"""
    return _cut(f'{person(actor)}님이 {inquiry.inquiry_no}에 코멘트를 남겼습니다')


def status_changed(inquiry, new_status, actor):
    """상태 변경 → 요청자에게 (담당자 이름 대신 직무)"""
    label = Inquiry.Status(new_status).label
    return _cut(f"{staff_display(actor)}가 {inquiry.inquiry_no} 문의를 '{label}'{euro(label)} 변경했습니다")
