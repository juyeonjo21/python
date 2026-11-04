"""
화면 확인용 샘플 데이터 만들기

사용법:
    python manage.py seed_data          # 샘플 데이터 생성 (이미 있으면 건너뜀)
    python manage.py seed_data --reset  # 샘플 문의·공지를 지우고 다시 생성

※ 개발 모드(DEBUG=True)에서만 실행됩니다.
※ 계정 비밀번호는 .env의 SEED_PASSWORD 값을 사용합니다.
"""

import random
from datetime import timedelta

import environ
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Department, Job, User
from inquiries.models import Category, Comment, History, Inquiry, RelatedInquiry
from notices.models import Notice
from notifications import messages as notice_messages
from notifications.models import EmailLog, Notification

S = Inquiry.Status  # 짧게 쓰기 위한 별칭

# ------------------------------------------------------------
# 샘플 데이터 정의
# ------------------------------------------------------------
DEPARTMENTS = ['EMC', 'Safety', 'Medical', '영업', '무선', '품질', '회계', '경영지원실']

CATEGORIES = [
    # (이름, 정렬 순서, 추가 입력 항목)
    ('권한 요청', 1, [
        {'key': 'menu', 'label': '메뉴명', 'type': 'text', 'required': True},
        {'key': 'permission', 'label': '필요 권한', 'type': 'select',
         'options': ['조회', '등록', '수정', '승인'], 'required': True},
    ]),
    ('오류 신고', 2, [
        {'key': 'screen', 'label': 'ERP 화면명', 'type': 'text', 'required': True,
         'placeholder': '예: 시험 > 접수 등록'},
        {'key': 'occurred_at', 'label': '발생 일시', 'type': 'datetime', 'required': False},
        {'key': 'error_message', 'label': '오류 메시지', 'type': 'textarea', 'required': False,
         'placeholder': '화면에 표시된 오류 문구를 그대로 붙여 넣어 주세요.'},
    ]),
    ('개선 요청', 3, [
        {'key': 'current', 'label': '현재 방식', 'type': 'textarea', 'required': True},
        {'key': 'expected', 'label': '기대 효과', 'type': 'textarea', 'required': False},
    ]),
    ('기타 요청', 4, []),
]

# (아이디, 이름, 역할, 부서, 직무)
# 문의 관리·처리는 경영지원실 소속 담당자가 직무(백엔드/프론트/기획)별로 맡음
USERS = [
    ('admin', '서지원', User.Role.ADMIN, '경영지원실', ''),
    ('agent1', '한소영', User.Role.AGENT, '경영지원실', Job.BACKEND),
    ('agent2', '강태현', User.Role.AGENT, '경영지원실', Job.FRONTEND),
    ('agent3', '윤하은', User.Role.AGENT, '경영지원실', Job.PLANNING),
    ('user1', '김민준', User.Role.USER, 'EMC', ''),
    ('user2', '이서연', User.Role.USER, 'Safety', ''),
    ('user3', '박지훈', User.Role.USER, 'Medical', ''),
    ('user4', '최수아', User.Role.USER, '영업', ''),
    ('user5', '정도윤', User.Role.USER, '무선', ''),
]

# 분류별 문의 예시: (제목, 내용, 추가 입력값)
INQUIRY_SAMPLES = {
    '권한 요청': [
        ('시험성적서 발급 메뉴 권한 요청', '신규 입사자 시험성적서 발급 업무를 위해 권한을 요청드립니다.',
         {'menu': '시험성적서 > 발급', 'permission': '등록'}),
        ('매출 현황 조회 권한 요청', '월말 실적 보고를 위해 매출 현황 조회 권한이 필요합니다.',
         {'menu': '영업 > 매출 현황', 'permission': '조회'}),
        ('구매 요청 승인 권한 추가', '팀장 부재 시 대결 처리를 위해 구매 승인 권한을 요청합니다.',
         {'menu': '구매 > 구매 요청', 'permission': '승인'}),
        ('장비 교정 이력 수정 권한', '교정 이력 오기재 수정을 위해 수정 권한이 필요합니다.',
         {'menu': '장비 > 교정 이력', 'permission': '수정'}),
    ],
    '오류 신고': [
        ('견적서 PDF 출력 시 글자 깨짐', '견적서를 PDF로 출력하면 한글 일부가 네모로 표시됩니다.',
         {'screen': '영업 > 견적서', 'error_message': ''}),
        ('시험 접수 저장 버튼 오류', '시험 접수 화면에서 저장 버튼을 누르면 오류 창이 뜹니다.',
         {'screen': '시험 > 접수 등록', 'error_message': '처리 중 오류가 발생했습니다 (500)'}),
        ('거래처 검색 결과 누락', '거래처명으로 검색하면 일부 거래처가 조회되지 않습니다.',
         {'screen': '기준정보 > 거래처', 'error_message': ''}),
        ('전표 승인 후 상태 미반영', '전표 승인 후에도 목록에 미승인으로 표시됩니다.',
         {'screen': '회계 > 전표 관리', 'error_message': ''}),
        ('엑셀 다운로드 시간 초과', '시험 실적 엑셀 다운로드 시 시간 초과 오류가 납니다.',
         {'screen': '시험 > 실적 조회', 'error_message': 'Timeout'}),
    ],
    '개선 요청': [
        ('시험 일정 캘린더 보기 추가', '현재 목록으로만 볼 수 있어 일정 파악이 어렵습니다.',
         {'current': '목록 형태로만 조회', 'expected': '주간·월간 일정을 한눈에 확인'}),
        ('성적서 일괄 출력 기능', '성적서를 한 건씩 출력해야 해서 시간이 오래 걸립니다.',
         {'current': '건별 출력', 'expected': '출력 시간 단축'}),
        ('접수 화면 필수값 안내 개선', '어떤 항목이 필수인지 저장 후에야 알 수 있습니다.',
         {'current': '저장 시 오류로 안내', 'expected': '입력 실수 감소'}),
        ('장비 교정 만료 알림 메일', '교정 만료일을 놓치는 경우가 있어 사전 알림이 필요합니다.',
         {'current': '수동 확인', 'expected': '교정 누락 방지'}),
    ],
    '기타 요청': [
        ('ERP 사용 교육 일정 문의', '신규 입사자 대상 ERP 교육 일정이 궁금합니다.', {}),
        ('퇴사자 계정 정리 요청', '이번 달 퇴사자 2명의 계정 정리를 요청드립니다.', {}),
        ('부서 코드 변경 요청', '조직 개편에 따라 부서 코드 변경이 필요합니다.', {}),
    ],
}

# 상태별 건수 (합계 40건). 오래된 문의일수록 앞쪽 상태(처리 완료 등)를 받습니다.
STATUS_PLAN = [
    (S.CLOSED, 9), (S.REJECTED, 2), (S.ANSWERED, 7), (S.ON_HOLD, 3),
    (S.IN_PROGRESS, 8), (S.CHECKING, 5), (S.RECEIVED, 6),
]

HOLD_REASONS = ['요청 부서의 추가 자료 회신 대기 중입니다.', '차기 시스템 개편 일정과 함께 검토 예정입니다.']
REJECT_REASONS = ['보안 정책상 해당 권한은 부여할 수 없습니다.', '이미 동일한 기능이 제공되고 있어 반려합니다.']

NOTICES = [
    # (제목, 분류, 상단 고정, 내용)
    ('ERP 문의 관리 시스템 오픈 안내', Notice.Category.GENERAL, True,
     'ERP 관련 문의와 개선 요청은 이제 이 시스템으로 등록해 주세요.'),
    ('11월 정기 시스템 점검 안내', Notice.Category.MAINTENANCE, True,
     '11월 셋째 주 토요일 09:00~13:00 ERP 서비스가 중단됩니다.'),
    ('시험성적서 출력 양식 변경 안내', Notice.Category.UPDATE, False,
     '성적서 하단 서명란 위치가 변경되었습니다.'),
    ('신규 입사자 ERP 기초 교육', Notice.Category.TRAINING, False,
     '매월 첫째 주 수요일 14시에 ERP 기초 교육을 진행합니다.'),
    ('권한 요청 시 작성 요령', Notice.Category.GENERAL, False,
     '권한 요청 시 메뉴명과 필요한 권한(조회/등록/수정/승인)을 정확히 적어 주세요.'),
    ('거래처 검색 기능 개선 배포', Notice.Category.UPDATE, False,
     '거래처 검색 시 약칭으로도 조회되도록 개선되었습니다.'),
]

# 공지 제목 → 관련 문의 카테고리
NOTICE_CATEGORY_LINKS = {
    '권한 요청 시 작성 요령': '권한 요청',
    '거래처 검색 기능 개선 배포': '오류 신고',
    '시험성적서 출력 양식 변경 안내': '개선 요청',
    '신규 입사자 ERP 기초 교육': '기타 요청',
}


class Command(BaseCommand):
    help = '화면 확인용 샘플 데이터를 만듭니다. (개발 모드 전용)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true', help='기존 문의·공지를 지우고 다시 만듭니다.'
        )

    @transaction.atomic  # 중간에 오류가 나면 전부 취소
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('운영 모드(DEBUG=False)에서는 샘플 데이터를 만들 수 없습니다.')

        password = environ.Env().str('SEED_PASSWORD', default='')
        if not password:
            raise CommandError('.env에 SEED_PASSWORD를 설정해 주세요.')

        random.seed(42)  # 실행할 때마다 같은 결과가 나오도록 고정
        self.now = timezone.now()

        if options['reset']:
            self._reset()

        departments = self._create_departments()
        categories = self._create_categories()
        users = self._create_users(departments, password)

        if Inquiry.objects.exists():
            self.stdout.write(self.style.WARNING(
                '문의 데이터가 이미 있어 문의·공지 생성은 건너뜁니다. (다시 만들려면 --reset)'
            ))
        else:
            self._create_inquiries(categories, users)
            self._create_notices(users['admin'])
        self._link_notices(categories)
        self._create_notifications(users)

        self.stdout.write(self.style.SUCCESS(
            f'완료: 부서 {Department.objects.count()}개, 분류 {Category.objects.count()}개, '
            f'사용자 {User.objects.count()}명, 문의 {Inquiry.objects.count()}건, '
            f'답변 {Comment.objects.count()}건, 이력 {History.objects.count()}건, '
            f'공지 {Notice.objects.count()}건, 웹 알림 {Notification.objects.count()}건'
        ))

    # --------------------------------------------------------
    # 초기화 (개발용 명령이므로 예외적으로 실제 삭제)
    # --------------------------------------------------------
    def _reset(self):
        Notification.objects.all().delete()
        EmailLog.objects.all().delete()
        RelatedInquiry.objects.all().delete()
        History.objects.all().delete()  # 이력이 문의를 보호(PROTECT)하므로 먼저 삭제
        Inquiry.objects.all().delete()  # 답변·첨부도 함께 삭제됨
        Notice.objects.all().delete()
        self.stdout.write('기존 문의·공지 데이터를 삭제했습니다.')

    # --------------------------------------------------------
    # 부서·분류·사용자 (있으면 그대로 두고, 없으면 생성)
    # --------------------------------------------------------
    def _create_departments(self):
        return {
            name: Department.objects.get_or_create(name=name)[0]
            for name in DEPARTMENTS
        }

    def _create_categories(self):
        result = {}
        for name, order, fields in CATEGORIES:
            category, _ = Category.objects.update_or_create(
                name=name, parent=None,
                defaults={'sort_order': order, 'extra_fields': fields},
            )
            result[name] = category
        return result

    def _create_users(self, departments, password):
        result = {}
        for username, name, role, dept_name, job in USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'name': name,
                    'email': f'{username}@example.com',
                    'role': role,
                    'department': departments[dept_name],
                    'job': job,
                    # 담당자·관리자는 Django Admin에 들어갈 수 있게 함
                    'is_staff': role != User.Role.USER,
                    'is_superuser': role == User.Role.ADMIN,
                },
            )
            if created:
                user.set_password(password)  # 비밀번호는 암호화해서 저장
                user.save()
            if role != User.Role.USER and (user.department != departments[dept_name] or user.job != job):
                # 이미 있던 담당자·관리자 계정도 경영지원실·직무로 맞춤
                user.department, user.job = departments[dept_name], job
                user.save(update_fields=['department', 'job'])
            result[username] = user
        return result

    # --------------------------------------------------------
    # 문의 40건 + 답변·이력
    # --------------------------------------------------------
    def _create_inquiries(self, categories, users):
        requesters = [u for u in users.values() if u.role == User.Role.USER]
        agents = [u for u in users.values() if u.role == User.Role.AGENT]

        statuses = [status for status, count in STATUS_PLAN for _ in range(count)]
        # 최근 90일 안의 등록일시를 오래된 순으로 만듦 → 문의번호도 날짜 순서대로 붙음
        dates = sorted(
            self.now - timedelta(days=random.uniform(0, 90), hours=random.uniform(0, 8))
            for _ in statuses
        )

        samples = [(cat, *s) for cat, items in INQUIRY_SAMPLES.items() for s in items]
        created = []
        for created_at, status in zip(dates, statuses):
            cat_name, title, content, extra = random.choice(samples)
            requester = random.choice(requesters)
            agent = random.choice(agents)
            priority = random.choices(
                list(Inquiry.Priority), weights=[2, 6, 3, 1]
            )[0]
            inquiry = self._create_one_inquiry(
                categories[cat_name], title, content, extra,
                requester, agent, users['admin'], status, priority, created_at,
            )
            created.append(inquiry)

        # 같은 분류(오류 신고) 문의끼리 관련 문의로 몇 건 연결
        errors = [i for i in created if i.category.name == '오류 신고']
        for a, b in zip(errors[::2], errors[1::2][:3]):
            RelatedInquiry.objects.create(inquiry=a, related=b, note='유사 오류 신고')

    def _create_one_inquiry(self, category, title, content, extra, requester, agent,
                            admin, status, priority, created_at):
        """문의 1건과 그 처리 과정(답변·이력)을 시간 순서대로 만든다."""
        clock = Clock(created_at, self.now)

        reason = ''
        if status == S.ON_HOLD:
            reason = random.choice(HOLD_REASONS)
        elif status == S.REJECTED:
            reason = random.choice(REJECT_REASONS)
        elif status in (S.ANSWERED, S.CLOSED):
            reason = '요청하신 내용 처리를 완료했습니다.'

        inquiry = Inquiry.objects.create(
            title=title, content=content, category=category, extra_data=extra,
            requester=requester, priority=priority, status=status, resolution=reason,
            assigned_job='' if status == S.RECEIVED else agent.job,
        )
        log = HistoryWriter(inquiry)
        log.add(requester, History.Action.CREATE, '', S.RECEIVED.label, clock.at())

        if status == S.RECEIVED:
            return self._stamp_inquiry(inquiry, created_at, clock.last)

        # 접수 → 담당자 지정 → 확인 중
        log.add(admin, History.Action.ASSIGN, '', agent.get_job_display(), clock.next())
        log.add(agent, History.Action.STATUS, S.RECEIVED.label, S.CHECKING.label, clock.next())

        if status == S.REJECTED:
            log.add(agent, History.Action.STATUS, S.CHECKING.label, S.REJECTED.label,
                    clock.next(), memo=reason)
            return self._stamp_inquiry(inquiry, created_at, clock.last)
        if status == S.CHECKING:
            return self._stamp_inquiry(inquiry, created_at, clock.last)

        # 확인 중 → 처리 중
        log.add(agent, History.Action.STATUS, S.CHECKING.label, S.IN_PROGRESS.label, clock.next())
        if random.random() < 0.5:
            add_comment(inquiry, agent, Comment.Type.INTERNAL,
                        '관련 설정을 확인 중입니다. 운영 DB 반영 전 테스트 필요.', clock.next())
        if random.random() < 0.3:
            add_comment(inquiry, requester, Comment.Type.USER,
                        '진행 상황 공유 부탁드립니다.', clock.next())

        if status == S.ON_HOLD:
            log.add(agent, History.Action.STATUS, S.IN_PROGRESS.label, S.ON_HOLD.label,
                    clock.next(), memo=reason)
            return self._stamp_inquiry(inquiry, created_at, clock.last)
        if status == S.IN_PROGRESS:
            return self._stamp_inquiry(inquiry, created_at, clock.last)

        # 처리 중 → 답변 완료
        answered_at = clock.next()
        add_comment(inquiry, agent, Comment.Type.ANSWER,
                    f'안녕하세요, ERP 담당자 {agent.name}입니다.\n요청하신 내용 처리를 완료했습니다. 확인 부탁드립니다.',
                    answered_at)
        log.add(agent, History.Action.COMMENT, '', '답변 등록', answered_at)
        log.add(agent, History.Action.STATUS, S.IN_PROGRESS.label, S.ANSWERED.label, answered_at)
        resolved_at = answered_at

        closed_at = None
        if status == S.CLOSED:
            if random.random() < 0.5:
                add_comment(inquiry, requester, Comment.Type.USER,
                            '확인했습니다. 감사합니다.', clock.next())
            closed_at = clock.next()
            log.add(agent, History.Action.STATUS, S.ANSWERED.label, S.CLOSED.label, closed_at)

        return self._stamp_inquiry(inquiry, created_at, clock.last, resolved_at, closed_at)

    def _stamp_inquiry(self, inquiry, created_at, updated_at, resolved_at=None, closed_at=None):
        """
        자동으로 '지금 시각'이 들어간 날짜를 샘플용 과거 날짜로 바꿈.
        (queryset.update는 save()를 거치지 않아 auto_now 값을 덮어쓸 수 있음)
        """
        Inquiry.objects.filter(pk=inquiry.pk).update(
            created_at=created_at, updated_at=updated_at,
            resolved_at=resolved_at, closed_at=closed_at,
        )
        return inquiry

    # --------------------------------------------------------
    # 공지 6건
    # --------------------------------------------------------
    def _create_notices(self, author):
        for days_ago, (title, category, pinned, content) in zip([60, 20, 45, 30, 10, 3], NOTICES):
            notice = Notice.objects.create(
                title=title, category=category, is_pinned=pinned, content=content, author=author,
            )
            when = self.now - timedelta(days=days_ago)
            Notice.objects.filter(pk=notice.pk).update(created_at=when, updated_at=when)

    # --------------------------------------------------------
    # 웹 알림 샘플 (계정마다 안 읽은 3~5개 + 읽은 몇 개)
    # --------------------------------------------------------
    def _create_notifications(self, users):
        if Notification.objects.exists():
            self.stdout.write('웹 알림이 이미 있어 샘플 알림 생성은 건너뜁니다.')
            return
        rng = random.Random(7)
        E = Notification.EventType
        admin = users['admin']
        staff_by_job = {u.job: u for u in users.values() if u.job}
        open_inquiries = Inquiry.objects.exclude(status__in=[S.CLOSED, S.REJECTED]).select_related('requester')

        for user in users.values():
            items = []  # (상황, 문의, 행동한 사람, 문장) - 최신 것부터
            if user.role == User.Role.USER:
                # 요청자: 내 문의의 진행 과정 알림 (담당자 이름 대신 직무로 표시)
                # '접수' 상태 문의는 아직 아무 변화가 없으므로 제외
                for inq in (Inquiry.objects.filter(requester=user).exclude(status=S.RECEIVED)
                            .order_by('-updated_at')[:5]):
                    actor = staff_by_job.get(inq.assigned_job, admin)
                    if inq.status == S.CLOSED:
                        items.append((E.STATUS_CHANGED, inq, actor, notice_messages.status_changed(inq, S.CLOSED, actor)))
                    if inq.status in (S.ANSWERED, S.CLOSED):
                        items.append((E.ANSWERED, inq, actor, notice_messages.answered(inq, actor)))
                    else:
                        items.append((E.STATUS_CHANGED, inq, actor, notice_messages.status_changed(inq, inq.status, actor)))
                    if inq.status != S.CHECKING:  # 더 이전 단계: 확인 중으로 바뀐 알림
                        items.append((E.STATUS_CHANGED, inq, actor, notice_messages.status_changed(inq, S.CHECKING, actor)))
            else:
                # 담당자: 내 직무에 배정된 문의 + 새 문의 + 요청자 코멘트
                if user.job:
                    for inq in open_inquiries.filter(assigned_job=user.job).order_by('-updated_at')[:3]:
                        items.append((E.ASSIGNED, inq, admin,
                                      notice_messages.assigned(inq, user.get_job_display(), admin)))
                for inq in open_inquiries.filter(assigned_job='').exclude(requester=user).order_by('-created_at')[:4]:
                    items.append((E.CREATED, inq, inq.requester, notice_messages.created(inq)))
                for inq in open_inquiries.filter(assigned_job=user.job or '').order_by('created_at')[:2]:
                    items.append((E.COMMENTED, inq, inq.requester, notice_messages.commented(inq, inq.requester)))

            items = items[:8]
            # 안 읽은 알림 3~5개를 먼저 채우고, 남는 것은 읽은 알림
            # (실제로 일어난 일만 알림으로 만들기 때문에 문의가 적은 계정은 읽은 알림이 없을 수 있음)
            unread_count = min(rng.randint(3, 5), len(items))
            if len(items) - unread_count < 2 and len(items) >= 5:
                unread_count = len(items) - 2
            hours = 0
            for index, (event_type, inq, actor, message) in enumerate(items):
                hours += rng.randint(2, 20)
                created_at = self.now - timedelta(hours=hours)
                notification = Notification.objects.create(
                    recipient=user, inquiry=inq, actor=actor, event_type=event_type, message=message,
                )
                is_read = index >= unread_count
                Notification.objects.filter(pk=notification.pk).update(
                    created_at=created_at, is_read=is_read,
                    read_at=created_at + timedelta(hours=1) if is_read else None,
                )

    def _link_notices(self, categories):
        """샘플 공지를 관련 문의 카테고리와 연결 (문의 등록 화면 참고 패널용)"""
        for title, category_name in NOTICE_CATEGORY_LINKS.items():
            Notice.objects.filter(title=title, inquiry_category__isnull=True).update(
                inquiry_category=categories[category_name]
            )


# ------------------------------------------------------------
# 샘플 생성을 돕는 작은 도구들
# ------------------------------------------------------------
class Clock:
    """처리 단계마다 몇 시간씩 시간을 앞으로 보내는 가상의 시계 (현재 시각은 넘지 않음)"""

    def __init__(self, start, limit):
        self.last = start
        self.limit = limit

    def at(self):
        return self.last

    def next(self):
        step = timedelta(hours=random.uniform(1, 30))
        self.last = min(self.last + step, self.limit - timedelta(minutes=1))
        return self.last


class HistoryWriter:
    """문의 1건의 이력을 남기고, 등록일시를 원하는 과거 시각으로 맞춘다."""

    def __init__(self, inquiry):
        self.inquiry = inquiry

    def add(self, actor, action, from_value, to_value, when, memo=''):
        history = History.objects.create(
            inquiry=self.inquiry, actor=actor, action=action,
            from_value=from_value, to_value=to_value, memo=memo,
        )
        # History.save()는 수정을 막으므로 queryset.update로 날짜만 맞춤 (샘플 전용)
        History.objects.filter(pk=history.pk).update(created_at=when)


def add_comment(inquiry, author, comment_type, content, when):
    comment = Comment.objects.create(
        inquiry=inquiry, author=author, type=comment_type, content=content,
    )
    Comment.objects.filter(pk=comment.pk).update(created_at=when)
