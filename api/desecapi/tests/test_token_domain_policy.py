from rest_framework import status

from desecapi.models import Token
from desecapi.tests.base import DomainOwnerTestCase


class TokenDomainPolicyTestCase(DomainOwnerTestCase):

    def setUp(self):
        super().setUp()
        self.token.perm_manage_tokens = True
        self.token.save()
        self.token2 = self.create_token(self.owner, name='testtoken')
        self.other_token = self.create_token(self.user)

    def test_list_domains(self):
        response = self.client.get(self.reverse('v1:domain-list'))
        self.assertStatus(response, status.HTTP_200_OK)
