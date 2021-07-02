from django.urls import include, path


#
# On Reversing URLs
# =================
#
# Recommended Usage:
# Always use rest_framework.reverse.reverse, do not directly use django.urls.reverse.
# If a request object r is available, use reverse(name, request=r). With the name as defined
# in desecapi.urls.v1 or desecapi.urls.v2. It will return an URL maintaining the currently requested API version.
# If there is no request object available, e.g. in commands, a mock object can be constructed
# carrying all information that is necessary to construct a full URL:
#
#         from django.conf import settings
#         from django.test import RequestFactory
#         from rest_framework.versioning import NamespaceVersioning
#
#         r = RequestFactory().request(HTTP_HOST=settings.ALLOWED_HOSTS[0])
#         r.version = 'v1'
#         r.versioning_scheme = NamespaceVersioning()
#
# Also note in this context settings.REST_FRAMEWORK['ALLOWED_VERSIONS'] and
# settings.REST_FRAMEWORK['DEFAULT_VERSIONING_CLASS']. (The latter is of type string.)
#
# Advanced Usage:
# Prefix the name of any path with 'desecapi' to get the default version,
# or prefix the name of any path with the desired namespace, e.g. 'v1:root'.
# In this case, the version information of the request will be ignored and
# providing a request object is optional. However, if no request object is provided,
# only a relative URL can be generated.
#
# Examples:
# The examples refer to the version used by the client to connect as the REQUESTED version,
# the version specified by the first argument to reverse as the SPECIFIED version, and to the
# version defined as default (see below) as the DEFAULT version.
#
#         reverse('root', request) -> absolute URL, e.g. https://.../api/v1/, with the REQUESTED version
#         reverse('root') -> django.urls.exceptions.NoReverseMatch
#         reverse('desecapi:root') -> relative URL, e.g. api/v1/, with the DEFAULT version
#         reverse('v2:root') -> relative URL, e.g. api/v2/, with the SPECIFIED version
#         reverse('v2:root', request) -> absolute URL, e.g. https://.../api/v2/, with the SPECIFIED version
#         reverse('desecapi:root', request) -> absolute URL, e.g. https://.../api/v1/, with the DEFAULT version
#         reverse('v1:root', request) -> absolute URL, e.g. https://.../api/v1/, with the SPECIFIED version
#
# See Also:
# https://github.com/encode/django-rest-framework/issues/5659
# https://github.com/encode/django-rest-framework/issues/3825
#
# Note that from the client's perspective, there is no default version: each request needs to
# specify the version in the request URL.
#

# IMPORTANT: specify default version as the last element in the list
# if no other information is available, the last-specified version will be used as default for reversing URLs
urlpatterns = [
    # other available versions in no particular order
    #path('api/v2/', include('desecapi.urls.version_2', namespace='v2')),
    # the DEFAULT version
    path('api/v1/', include('desecapi.urls.version_1', namespace='v1')),
    # monitoring
    path('', include('django_prometheus.urls')),
]
