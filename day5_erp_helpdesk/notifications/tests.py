"""
알림(웹 알림·이메일) 테스트

실행: python manage.py test notifications

- 메일은 테스트용 메모리 백엔드에 쌓임 → mail.outbox 로 확인 (Django 테스트가 자동 설정)
- 알림은 DB 저장이 끝난 뒤(on_commit) 실행되므로,
  captureOnCommitCallbacks(execute=True)로 감싸서 실제처럼 실행시킨다
"""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department, Job, User
from inquiries import services
from inquiries.models import Category, Comment, Inquiry

from .inapp import mark_all_read, mark_inquiry_read, mark_read
from .models import EmailLog, Notification

S = Inquiry.Status
E = Notification.EventType


@override_settings(EMAIL_REDIRECT_TO='', SITE_URL='http://testserver')
class NotificationTestBase(TestCase):
    """테스트용 계정·카테고리 준비 + 자주 쓰는 도우미"""

    @classmethod
    def setUpTestData(cls):
        office = Department.objects.create(name='경영지원실')
        emc = Department.objects.create(name='EMC')
        cls.category = Category.objects.create(name='오류 신고')

        def make(username, role, job='', email=None, dept=office):
            return User.objects.create_user(
                username=username, password='pw', name=username, role=role, job=job, department=dept,
                email=f'{username}@test.local' if email is None else email,
            )

        cls.admin = make('admin', User.Role.ADMIN)                       # 직무 없음
        cls.backend = make('backend', User.Role.AGENT, Job.BACKEND)
        cls.frontend = make('frontend', User.Role.AGENT, Job.FRONTEND)
        cls.planner = make('planner', User.Role.AGENT, Job.PLANNING, email='')  # 이메일 없는 담당자
        cls.user = make('user1', User.Role.USER, dept=emc)
        cls.staff = {cls.admin, cls.backend, cls.frontend, cls.planner}

    # ── 도우미 ──
    def run_on_commit(self):
        return self.captureOnCommitCallbacks(execute=True)

    def create(self, priority=Inquiry.Priority.NORMAL, requester=None):
        with self.run_on_commit():
            return services.create_inquiry(
                requester=requester or self.user, category=self.category,
                title='전표 저장 오류', content='저장하면 오류가 납니다.', priority=priority,
            )

    def reset(self):
        """앞 단계에서 생긴 알림·메일을 지우고 다음 동작만 확인"""
        Notification.objects.all().delete()
        mail.outbox.clear()

    def web(self, **filters):
        return Notification.objects.filter(**filters)

    def recipients(self, **filters):
        return set(User.objects.filter(notifications__in=self.web(**filters)))

    def mail_to(self):
        return sorted(address for m in mail.outbox for address in m.to)


class CreatedTests(NotificationTestBase):
    def test_보통_문의_등록은_담당자_전원_웹알림만_메일없음(self):
        inquiry = self.create()
        self.assertEqual(self.recipients(event_type=E.CREATED), self.staff)
        self.assertFalse(self.web(recipient=self.user).exists(), '요청자 접수 확인 알림은 꺼져 있어야 함')
        self.assertEqual(mail.outbox, [])
        message = self.web(recipient=self.backend).get().message
        self.assertEqual(message, f'user1님이 {inquiry.inquiry_no} 문의를 등록했습니다')

    def test_이메일_주소가_없는_담당자도_웹알림은_받음(self):
        self.create(priority=Inquiry.Priority.URGENT)
        self.assertTrue(self.web(recipient=self.planner, event_type=E.CREATED).exists())
        self.assertNotIn('', self.mail_to())

    def test_긴급_문의는_이메일_있는_담당자에게만_메일(self):
        self.create(priority=Inquiry.Priority.URGENT)
        self.assertEqual(self.mail_to(), ['admin@test.local', 'backend@test.local', 'frontend@test.local'])
        self.assertIn('새 문의', mail.outbox[0].subject)

    def test_담당자가_직접_등록하면_본인은_알림을_받지_않음(self):
        self.create(requester=self.backend)
        self.assertEqual(self.recipients(event_type=E.CREATED), self.staff - {self.backend})


class AnswerAndCommentTests(NotificationTestBase):
    def setUp(self):
        self.inquiry = self.create()
        self.reset()

    def test_답변은_요청자에게_웹알림_1개와_메일_1통만(self):
        with self.run_on_commit():
            services.add_comment(self.inquiry, self.backend, Comment.Type.ANSWER, '수정했습니다.')
        self.inquiry.refresh_from_db()
        # 답변하면서 직무 자동 지정·답변 완료 자동 변경이 함께 일어났지만
        self.assertEqual(self.inquiry.assigned_job, Job.BACKEND)
        self.assertEqual(self.inquiry.status, S.ANSWERED)
        # 알림은 답변 1건만
        self.assertEqual(Notification.objects.count(), 1)
        notification = Notification.objects.get()
        self.assertEqual((notification.recipient, notification.event_type), (self.user, E.ANSWERED))
        self.assertEqual(notification.message, f'ERP 담당자(백엔드)가 {self.inquiry.inquiry_no}에 답변을 등록했습니다')
        self.assertNotIn('backend', notification.message, '요청자에게는 담당자 이름 대신 직무')
        self.assertEqual(self.mail_to(), ['user1@test.local'])
        self.assertIn('답변 등록', mail.outbox[0].subject)

    def test_내부_메모는_알림_없음(self):
        with self.run_on_commit():
            services.add_comment(self.inquiry, self.backend, Comment.Type.INTERNAL, '내부 확인')
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_사용자_코멘트는_배정_직무_담당자에게_웹알림만(self):
        with self.run_on_commit():
            services.assign(self.inquiry, self.admin, Job.FRONTEND)
        self.reset()
        with self.run_on_commit():
            services.add_comment(self.inquiry, self.user, Comment.Type.USER, '여전히 오류가 나요')
        self.assertEqual(self.recipients(event_type=E.COMMENTED), {self.frontend})
        self.assertEqual(mail.outbox, [])

    def test_미배정_문의의_사용자_코멘트는_담당자_전원에게(self):
        with self.run_on_commit():
            services.add_comment(self.inquiry, self.user, Comment.Type.USER, '추가 질문입니다')
        self.assertEqual(self.recipients(event_type=E.COMMENTED), self.staff)


class StatusAndAssignTests(NotificationTestBase):
    def setUp(self):
        self.inquiry = self.create()
        self.reset()

    def test_처리중_변경은_요청자에게_웹알림만(self):
        with self.run_on_commit():
            services.change_status(self.inquiry, self.backend, S.IN_PROGRESS)
        notification = self.web(recipient=self.user).get()
        self.assertEqual(notification.event_type, E.STATUS_CHANGED)
        self.assertEqual(notification.message,
                         f"ERP 담당자(백엔드)가 {self.inquiry.inquiry_no} 문의를 '처리 중'으로 변경했습니다")
        self.assertEqual(mail.outbox, [])

    def test_처리완료_변경은_웹알림과_메일(self):
        with self.run_on_commit():
            services.change_status(self.inquiry, self.backend, S.CLOSED, reason='배포 완료')
        self.assertEqual(self.recipients(event_type=E.STATUS_CHANGED), {self.user})
        self.assertEqual(self.mail_to(), ['user1@test.local'])
        self.assertIn('처리 완료', mail.outbox[0].subject)

    def test_보류_메일에는_사유_포함(self):
        with self.run_on_commit():
            services.change_status(self.inquiry, self.backend, S.ON_HOLD, reason='자료 회신 대기')
        self.assertIn('자료 회신 대기', mail.outbox[0].body)

    def test_직무_지정은_그_직무_담당자에게_웹알림만_자동_확인중_알림없음(self):
        with self.run_on_commit():
            services.assign(self.inquiry, self.admin, Job.BACKEND)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, S.CHECKING)  # 접수 → 확인 중 자동 변경은 됐지만
        self.assertEqual(set(Notification.objects.values_list('event_type', flat=True)), {E.ASSIGNED})
        self.assertEqual(self.recipients(), {self.backend})
        self.assertEqual(mail.outbox, [])

    def test_본인_직무로_지정하면_본인에게는_알림없음(self):
        with self.run_on_commit():
            services.assign(self.inquiry, self.frontend, Job.FRONTEND)
        self.assertFalse(self.web(event_type=E.ASSIGNED).exists())

    def test_본인이_요청자이면_상태변경_알림없음(self):
        inquiry = self.create(requester=self.backend)
        self.reset()
        with self.run_on_commit():
            services.change_status(inquiry, self.backend, S.CLOSED, reason='직접 해결')
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(mail.outbox, [])


class FailureTests(NotificationTestBase):
    def test_웹알림_생성이_실패해도_문의_등록은_성공하고_메일은_발송(self):
        self.client.force_login(self.user)
        with mock.patch('notifications.inapp.Notification.objects.bulk_create', side_effect=DatabaseError('DB 오류')):
            with self.assertLogs('notifications.inapp', level='ERROR'), self.run_on_commit():
                response = self.client.post(reverse('inquiries:create'), {
                    'category': self.category.pk, 'priority': Inquiry.Priority.URGENT,
                    'title': '웹 알림 장애 중 등록', 'content': '내용입니다',
                })
        inquiry = Inquiry.objects.get(title='웹 알림 장애 중 등록')
        self.assertRedirects(response, reverse('inquiries:detail', args=[inquiry.inquiry_no]),
                             fetch_redirect_response=False)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 3, '웹 알림이 실패해도 긴급 메일은 나가야 함')
        self.assertEqual(EmailLog.objects.filter(status=EmailLog.Status.SENT).count(), 3)


class ReadTests(NotificationTestBase):
    def setUp(self):
        self.first = self.create()
        self.second = self.create()

    def test_문의_상세를_열면_그_문의의_내_알림만_읽음(self):
        self.client.force_login(self.backend)
        response = self.client.get(reverse('inquiries:detail', args=[self.first.inquiry_no]))
        self.assertEqual(response.status_code, 200)
        mine = self.web(recipient=self.backend)
        self.assertTrue(mine.get(inquiry=self.first).is_read)
        self.assertIsNotNone(mine.get(inquiry=self.first).read_at)
        self.assertFalse(mine.get(inquiry=self.second).is_read, '다른 문의 알림은 그대로')
        self.assertFalse(self.web(recipient=self.frontend, inquiry=self.first).get().is_read, '남의 알림은 그대로')

    def test_mark_read는_본인_알림만(self):
        others = self.web(recipient=self.frontend).first()
        self.assertEqual(mark_read(self.backend, others), 0)
        mine = self.web(recipient=self.backend).first()
        self.assertEqual(mark_read(self.backend, mine), 1)

    def test_mark_all_read와_mark_inquiry_read(self):
        self.assertEqual(mark_inquiry_read(self.backend, self.first), 1)
        self.assertEqual(mark_all_read(self.backend), 1)
        self.assertFalse(self.web(recipient=self.backend, is_read=False).exists())


class CleanupCommandTests(NotificationTestBase):
    def test_읽은지_오래된_알림만_삭제_dry_run은_삭제안함(self):
        self.create()  # 담당자 4명에게 알림 4개
        old = timezone.now() - timedelta(days=100)
        notifications = list(Notification.objects.order_by('pk'))
        Notification.objects.filter(pk=notifications[0].pk).update(is_read=True, read_at=old)            # 삭제 대상
        Notification.objects.filter(pk=notifications[1].pk).update(is_read=True, read_at=timezone.now())  # 최근에 읽음
        Notification.objects.filter(pk=notifications[2].pk).update(created_at=old)                      # 오래됐지만 안 읽음

        out = StringIO()
        call_command('cleanup_notifications', '--dry-run', stdout=out)
        self.assertIn('1건', out.getvalue())
        self.assertEqual(Notification.objects.count(), 4)

        call_command('cleanup_notifications', '--days', '90', stdout=StringIO())
        self.assertEqual(Notification.objects.count(), 3)
        self.assertFalse(Notification.objects.filter(pk=notifications[0].pk).exists())


# ============================================================
# 웹 알림 화면 (배지·패널·알림 클릭·전체 페이지·홈·메일 링크)
# ============================================================
from .context_processors import display_count  # noqa: E402


class NotificationScreenTests(NotificationTestBase):
    def setUp(self):
        self.first = self.create()     # 담당자들에게 '새 문의' 알림
        self.second = self.create()
        self.client.force_login(self.backend)

    def mine(self, **filters):
        return self.web(recipient=self.backend, **filters)

    def test_배지_숫자_표시_99개_초과는_99플러스(self):
        self.assertEqual([display_count(n) for n in (0, 3, 99, 100)], ['', '3', '99', '99+'])

    def test_모든_화면에_안읽은_개수와_탭제목(self):
        response = self.client.get(reverse('inquiries:list'))
        self.assertEqual(response.context['unread_count'], 2)
        self.assertContains(response, '<title>(2) 전체 문의 · ERP Helpdesk</title>', html=False)
        for badge_id in ('notif-badge-sidebar', 'notif-badge-mobile', 'notif-badge-nav'):
            self.assertContains(response, f'id="{badge_id}"')

    def test_배지_주소는_개수만_가볍게_oob로(self):
        response = self.client.get(reverse('notifications:badge'))
        self.assertEqual(response['X-Unread-Count'], '2')
        self.assertContains(response, 'hx-swap-oob="true"', count=3)
        self.assertContains(response, '안 읽은 알림 2개', count=3)

    def test_패널은_최근_10개_안읽음_탭은_안읽은것만(self):
        mark_read(self.backend, self.mine(inquiry=self.first).get())
        all_tab = self.client.get(reverse('notifications:panel'))
        self.assertEqual(len(all_tab.context['items']), 2)
        unread_tab = self.client.get(reverse('notifications:panel'), {'tab': 'unread'})
        self.assertEqual([n.inquiry for n in unread_tab.context['items']], [self.second])
        self.assertEqual(unread_tab['X-Unread-Count'], '1')

    def test_빈_패널은_empty_state(self):
        mark_all_read(self.backend)
        response = self.client.get(reverse('notifications:panel'), {'tab': 'unread'})
        self.assertContains(response, '새 알림이 없습니다')

    def test_모두_읽음은_POST만_패널과_배지_갱신(self):
        self.assertEqual(self.client.get(reverse('notifications:read_all')).status_code, 405)
        response = self.client.post(reverse('notifications:read_all'), {'tab': 'all'}, HTTP_HX_REQUEST='true')
        self.assertEqual(response['X-Unread-Count'], '0')
        self.assertFalse(self.mine(is_read=False).exists())
        self.assertFalse(self.web(recipient=self.frontend, is_read=True).exists(), '남의 알림은 그대로')

    def test_모두_읽음_일반요청은_원래_페이지로_외부주소는_무시(self):
        response = self.client.post(reverse('notifications:read_all'), {'next': '/notifications/?tab=unread'})
        self.assertRedirects(response, '/notifications/?tab=unread', fetch_redirect_response=False)
        response = self.client.post(reverse('notifications:read_all'), {'next': 'https://evil.example.com/'})
        self.assertRedirects(response, reverse('notifications:list'), fetch_redirect_response=False)

    def test_알림_클릭은_읽음처리_후_문의상세로(self):
        notification = self.mine(inquiry=self.first).get()
        response = self.client.get(reverse('notifications:go', args=[notification.pk]))
        self.assertRedirects(response, reverse('inquiries:detail', args=[self.first.inquiry_no]),
                             fetch_redirect_response=False)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_남의_알림_클릭은_404(self):
        others = self.web(recipient=self.frontend).first()
        self.assertEqual(self.client.get(reverse('notifications:go', args=[others.pk])).status_code, 404)

    def test_삭제된_문의_또는_권한없는_문의는_목록으로_안내(self):
        gone = Notification.objects.create(recipient=self.user, inquiry=None, event_type=E.ANSWERED, message='x')
        not_mine = Notification.objects.create(recipient=self.user, inquiry=self.create(requester=self.frontend),
                                               event_type=E.ANSWERED, message='y')
        self.client.force_login(self.user)
        for notification, text in ((gone, '삭제된 문의'), (not_mine, '볼 권한이 없습니다')):
            response = self.client.get(reverse('notifications:go', args=[notification.pk]), follow=True)
            self.assertEqual(response.redirect_chain[-1][0], reverse('notifications:list'))
            self.assertContains(response, text)

    def test_전체_알림_페이지_탭_필터_날짜묶음(self):
        old = self.mine(inquiry=self.first).get()
        Notification.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))
        response = self.client.get(reverse('notifications:list'))
        self.assertEqual([label for label, _ in response.context['groups']], ['오늘', '이전'])
        self.assertEqual([t['count'] for t in response.context['tabs']], [2, 2])
        response = self.client.get(reverse('notifications:list'), {'event': E.ANSWERED})
        self.assertEqual(response.context['groups'], [])
        self.assertContains(response, '새 알림이 없습니다')

    def test_전체_알림_페이지는_30개씩(self):
        Notification.objects.bulk_create([
            Notification(recipient=self.backend, inquiry=self.first, event_type=E.CREATED, message=f'알림 {i}')
            for i in range(40)
        ])
        response = self.client.get(reverse('notifications:list'))
        self.assertEqual(len(response.context['page_obj'].object_list), 30)

    def test_홈에_새_알림_카드_최대_5개(self):
        Notification.objects.bulk_create([
            Notification(recipient=self.backend, inquiry=self.first, event_type=E.CREATED, message=f'알림 {i}')
            for i in range(7)
        ])
        response = self.client.get(reverse('dashboard:home'))
        self.assertEqual(len(response.context['new_notifications']), 5)
        self.assertContains(response, '새 알림')

    def test_메일_링크로_로그인해서_들어와도_그_문의_알림_읽음(self):
        """메일의 '문의 확인하기' → 로그인 화면(next) → 로그인 → 문의 상세 → 읽음"""
        self.client.logout()
        detail = reverse('inquiries:detail', args=[self.first.inquiry_no])
        response = self.client.get(detail)
        login_url = f"{reverse('accounts:login')}?next={detail}"
        self.assertRedirects(response, login_url, fetch_redirect_response=False)
        response = self.client.post(login_url, {'username': 'backend', 'password': 'pw', 'next': detail}, follow=True)
        self.assertEqual(response.redirect_chain[-1][0], detail)
        self.assertTrue(self.mine(inquiry=self.first).get().is_read)
        self.assertFalse(self.mine(inquiry=self.second).get().is_read)
