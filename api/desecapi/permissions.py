from ipaddress import IPv4Address, IPv4Network

from rest_framework import permissions

from desecapi.models import TokenDomainPolicy


class IsOwner(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to view or edit it.
    """

    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user


class IsDomainOwner(permissions.BasePermission):
    """
    Custom permission to only allow owners of a domain to view or edit an object owned by that domain.
    """

    def has_object_permission(self, request, view, obj):
        return obj.domain.owner == request.user


class TokenDomainPolicyBasePermission(permissions.BasePermission):
    """
    Base permission to check whether a token authorizes specific actions on a domain.
    """
    perm_field = 'any_perm'

    def _has_object_permission(self, request, view, obj):
        ### TODO reduce number of queries?

        # Try domain-specific policy first
        try:
            return getattr(TokenDomainPolicy.objects.get(token=request.auth, domain=obj), self.perm_field)
        except TokenDomainPolicy.DoesNotExist:
            pass

        # Try general policy
        try:
            return getattr(TokenDomainPolicy.objects.get(token=request.auth, domain__isnull=True), self.perm_field)
        except TokenDomainPolicy.DoesNotExist:
            pass

        # Else, allow if and only if the token has no domain policy at all
        return not TokenDomainPolicy.objects.filter(token=request.auth).exists()


class TokenHasDomainObjectPermission(TokenDomainPolicyBasePermission):
    has_object_permission = TokenDomainPolicyBasePermission._has_object_permission


class TokenHasViewDomainPermission(TokenDomainPolicyBasePermission):

    def has_permission(self, request, view):
        return self._has_object_permission(request, view, view.domain)


class TokenHasViewDomainDynPermission(TokenHasViewDomainPermission):
    """
    Custom permission to check whether a token authorizes using the dynDNS interface for the view domain.
    """
    perm_field = 'perm_dyndns'


class IsVPNClient(permissions.BasePermission):
    """
    Permission that requires that the user is accessing using an IP from the VPN net.
    """
    message = 'Inadmissible client IP.'

    def has_permission(self, request, view):
        ip = IPv4Address(request.META.get('REMOTE_ADDR'))
        return ip in IPv4Network('10.8.0.0/24')


class ManageTokensPermission(permissions.BasePermission):

    def has_permission(self, request, view):
        return request.auth.perm_manage_tokens


class WithinDomainLimitOnPOST(permissions.BasePermission):
    """
    Permission that requires that the user still has domain limit quota available, if the request is using POST.
    """
    message = 'Domain limit exceeded. Please contact support to create additional domains.'

    def has_permission(self, request, view):
        if request.method != 'POST':
            return True

        return request.user.limit_domains is None or request.user.domains.count() < request.user.limit_domains
