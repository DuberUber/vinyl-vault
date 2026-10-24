from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()
PASSWORD = 'correct-horse-battery-staple'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SignupTests(TestCase):
    def signup(self, url=None, **overrides):
        data = {
            'username': 'newcustomer',
            'email': 'newcustomer@example.com',
            'password1': PASSWORD,
            'password2': PASSWORD,
            **overrides,
        }
        return self.client.post(url or reverse('accounts:signup'), data)

    def test_signup_creates_and_logs_in_the_user(self):
        response = self.signup()

        self.assertRedirects(response, reverse('catalog:home'))
        user = User.objects.get(username='newcustomer')
        self.assertEqual(user.email, 'newcustomer@example.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_weak_passwords_are_rejected(self):
        response = self.signup(password1='password', password2='password')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].has_error('password2'))
        self.assertFalse(User.objects.exists())

    def test_email_is_required_and_unique(self):
        User.objects.create_user('existing', email='NewCustomer@example.com')

        missing = self.signup(email='')
        duplicate = self.signup(email='newcustomer@EXAMPLE.com')

        self.assertTrue(missing.context['form'].has_error('email'))
        self.assertContains(duplicate, 'An account with this email address already exists.')

    def test_safe_next_url_is_followed(self):
        response = self.signup(url=f"{reverse('accounts:signup')}?next=/orders/")

        self.assertRedirects(response, '/orders/', fetch_redirect_response=False)

    def test_external_next_url_is_ignored(self):
        response = self.signup(url=f"{reverse('accounts:signup')}?next=https://evil.example.com/")

        self.assertRedirects(response, reverse('catalog:home'))

    def test_signed_in_users_are_redirected_away(self):
        self.client.force_login(User.objects.create_user('alex'))

        self.assertRedirects(self.client.get(reverse('accounts:signup')), reverse('catalog:home'))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LoginLogoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('alex', password=PASSWORD)

    def test_login_redirects_to_next(self):
        response = self.client.post(
            f"{reverse('accounts:login')}?next=/orders/cart/", {'username': 'alex', 'password': PASSWORD, 'next': '/orders/cart/'}
        )

        self.assertRedirects(response, '/orders/cart/')

    def test_wrong_password_shows_an_error(self):
        response = self.client.post(reverse('accounts:login'), {'username': 'alex', 'password': 'nope'})

        self.assertContains(response, 'Please enter a correct username and password.')

    def test_logout_requires_post_and_ends_the_session(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse('accounts:logout')).status_code, 405)
        response = self.client.post(reverse('accounts:logout'))

        self.assertRedirects(response, '/')
        self.assertNotIn('_auth_user_id', self.client.session)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('alex', email='alex@example.com', password=PASSWORD)

    def setUp(self):
        self.client.force_login(self.user)

    def test_profile_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse('accounts:profile'))

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('accounts:profile')}")

    def test_update_profile(self):
        response = self.client.post(
            reverse('accounts:profile'), {'first_name': 'Maeve', 'last_name': 'Kelly', 'email': 'maeve@example.com'},
            follow=True,
        )

        self.assertContains(response, 'Your details have been updated.')
        self.user.refresh_from_db()
        self.assertEqual((self.user.get_full_name(), self.user.email), ('Maeve Kelly', 'maeve@example.com'))

    def test_keeping_own_email_is_allowed_but_taking_anothers_is_not(self):
        User.objects.create_user('other', email='other@example.com')

        own = self.client.post(reverse('accounts:profile'), {'email': 'alex@example.com'})
        taken = self.client.post(reverse('accounts:profile'), {'email': 'OTHER@example.com'})

        self.assertEqual(own.status_code, 302)
        self.assertTrue(taken.context['form'].has_error('email'))

    def test_change_password(self):
        new_password = 'another-long-passphrase-42'

        response = self.client.post(reverse('accounts:password_change'), {
            'old_password': PASSWORD, 'new_password1': new_password, 'new_password2': new_password,
        })

        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
