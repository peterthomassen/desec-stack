from rest_framework import status

from desecapi.models import Token
from desecapi.tests.base import DomainOwnerTestCase


class TokenPermittedTestCase(DomainOwnerTestCase):

    def setUp(self):
        super().setUp()
        self.token.perm_manage_tokens = True
        self.token.save()
        self.token2 = self.create_token(self.owner, name='testtoken')
        self.other_token = self.create_token(self.user)

    def test_token_last_used(self):
        self.assertIsNone(Token.objects.get(pk=self.token.id).last_used)
        self.client.get(self.reverse('v1:root'))
        self.assertIsNotNone(Token.objects.get(pk=self.token.id).last_used)

    def test_list_tokens(self):
        response = self.client.get(self.reverse('v1:token-list'))
        self.assertStatus(response, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertIn('id', response.data[0])
        self.assertFalse(any(field in response.data[0] for field in ['token', 'key', 'value']))
        self.assertFalse(any(token.encode() in response.content for token in [self.token.plain, self.token2.plain]))
        self.assertNotContains(response, self.token.plain)

    def test_delete_my_token(self):
        token_id = Token.objects.get(user=self.owner, name='testtoken').id
        url = self.reverse('v1:token-detail', pk=token_id)

        response = self.client.delete(url)
        self.assertStatus(response, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Token.objects.filter(pk=token_id).exists())

        response = self.client.get(url)
        self.assertStatus(response, status.HTTP_404_NOT_FOUND)

    def test_retrieve_my_token(self):
        token_id = Token.objects.get(user=self.owner, name='testtoken').id
        url = self.reverse('v1:token-detail', pk=token_id)

        response = self.client.get(url)
        self.assertStatus(response, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data.keys()),
            {'id', 'created', 'last_used', 'max_age', 'max_unused_period', 'name', 'perm_manage_tokens',
             'allowed_subnets', 'is_valid'}
        )
        self.assertFalse(any(token.encode() in response.content for token in [self.token.plain, self.token2.plain]))

    def test_retrieve_other_token(self):
        token_id = Token.objects.get(user=self.user).id
        url = self.reverse('v1:token-detail', pk=token_id)

        response = self.client.get(url)
        self.assertStatus(response, status.HTTP_404_NOT_FOUND)

    def test_update_my_token(self):
        url = self.reverse('v1:token-detail', pk=self.token.id)

        for method in [self.client.patch, self.client.put]:
            datas = [
                {'name': method.__name__},
                {'allowed_subnets': ['127.0.0.0/8']},
                {'allowed_subnets': ['127.0.0.0/8', '::/0']},
                {'max_age': '365 00:10:33.123456'},
                {'max_age': None},
                {'max_unused_period': '365 00:10:33.123456'},
                {'max_unused_period': None},
            ]
            for data in datas:
                response = method(url, data=data)
                self.assertStatus(response, status.HTTP_200_OK)
                for k, v in data.items():
                    self.assertEqual(response.data[k], v)

        # Revoke token management permission
        response = self.client.patch(url, data={'perm_manage_tokens': False})
        self.assertStatus(response, status.HTTP_200_OK)

        # Verify that the change cannot be undone
        response = self.client.patch(url, data={'perm_manage_tokens': True})
        self.assertStatus(response, status.HTTP_403_FORBIDDEN)

    def test_create_token(self):
        n = len(Token.objects.filter(user=self.owner).all())

        datas = [
            {},
            {'name': '', 'perm_manage_tokens': True},
            {'name': 'foobar'},
            {'allowed_subnets': ['1.2.3.32/28', 'bade::affe/128']},
        ]
        for data in datas:
            response = self.client.post(self.reverse('v1:token-list'), data=data)
            self.assertStatus(response, status.HTTP_201_CREATED)
            self.assertEqual(
                set(response.data.keys()),
                {'id', 'created', 'last_used', 'max_age', 'max_unused_period', 'name', 'perm_manage_tokens',
                 'allowed_subnets', 'is_valid', 'token'}
            )
            self.assertEqual(response.data['name'], data.get('name', ''))
            self.assertEqual(response.data['allowed_subnets'], data.get('allowed_subnets', ['0.0.0.0/0', '::/0']))
            self.assertEqual(response.data['perm_manage_tokens'], data.get('perm_manage_tokens', False))
            self.assertIsNone(response.data['last_used'])

        self.assertEqual(len(Token.objects.filter(user=self.owner).all()), n + len(datas))


class TokenForbiddenTestCase(DomainOwnerTestCase):

    def setUp(self):
        super().setUp()
        self.token2 = self.create_token(self.owner, name='testtoken')
        self.other_token = self.create_token(self.user)

    def test_token_last_used(self):
        self.assertIsNone(Token.objects.get(pk=self.token.id).last_used)
        self.client.get(self.reverse('v1:root'))
        self.assertIsNotNone(Token.objects.get(pk=self.token.id).last_used)

    def test_list_tokens(self):
        response = self.client.get(self.reverse('v1:token-list'))
        self.assertStatus(response, status.HTTP_403_FORBIDDEN)

    def test_delete_my_token(self):
        for token_id in [Token.objects.get(user=self.owner, name='testtoken').id, self.token.id]:
            url = self.reverse('v1:token-detail', pk=token_id)
            response = self.client.delete(url)
            self.assertStatus(response, status.HTTP_403_FORBIDDEN)

    def test_retrieve_my_token(self):
        for token_id in [Token.objects.get(user=self.owner, name='testtoken').id, self.token.id]:
            url = self.reverse('v1:token-detail', pk=token_id)
            response = self.client.get(url)
            self.assertStatus(response, status.HTTP_403_FORBIDDEN)

    def test_retrieve_other_token(self):
        token_id = Token.objects.get(user=self.user).id
        url = self.reverse('v1:token-detail', pk=token_id)
        response = self.client.get(url)
        self.assertStatus(response, status.HTTP_403_FORBIDDEN)

    def test_update_my_token(self):
        url = self.reverse('v1:token-detail', pk=self.token.id)
        for method in [self.client.patch, self.client.put]:
            datas = [{'name': method.__name__}, {'allowed_subnets': ['127.0.0.0/8']}]
            for data in datas:
                response = method(url, data=data)
                self.assertStatus(response, status.HTTP_403_FORBIDDEN)

    def test_create_token(self):
        datas = [{}, {'name': ''}, {'name': 'foobar'}]
        for data in datas:
            response = self.client.post(self.reverse('v1:token-list'), data=data)
            self.assertStatus(response, status.HTTP_403_FORBIDDEN)
