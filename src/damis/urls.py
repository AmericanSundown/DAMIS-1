from django.conf.urls import patterns, url, include
from django.conf import settings
from django.conf.urls.i18n import i18n_patterns

from django.contrib.staticfiles.urls import staticfiles_urlpatterns

from damis.views import *


urlpatterns = patterns('',
    (r'^api/', include('damis.api.urls')),
    (r'^i18n/', include('django.conf.urls.i18n')),
    url(r'^api-token-auth/', 'rest_framework.authtoken.views.obtain_auth_token'),
)

urlpatterns += i18n_patterns('',
    (r'^jsi18n/$', 'django.views.i18n.javascript_catalog', {'domain': 'djangojs', 'packages': ('damis',), }, ),
    url(r'^$', index_view, name='home'),
    url(r'^about/$', static_page_view, name='about', kwargs={'template': 'index.html'}),
    url(r'^help/$', static_page_view, name='help', kwargs={'template': 'help.html'}),
    url(r'^faq/$', static_page_view, name='faq', kwargs={'template': 'faq.html'}),
    url(r'^404/$', static_page_view, name='404', kwargs={'template': '404.html'}),

    url(r'^login/$', login_view, name='login'),
    url(r'^logout/$', logout_view, name='logout'),
    url(r'^register/$', register_view, name='register'),
    url(r'^registration-done/$', static_page_view, name='registration-done',
        kwargs={'template': 'accounts/registration_done.html'}),
    url(r'^profile/$', profile_settings_view, name='profile-settings'),
    url(r'^reset-password/$', reset_password_view, name='reset-password'),
    url(r'^recover-password/(?P<uidb36>[0-9A-Za-z]{1,13})-(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
            recover_password_view, name='recover-password'),
    # User registers and gets welcome email with email confirm URL.
    url(r'^confirm-email/(?P<uidb36>[0-9A-Za-z]{1,13})-(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
        confirm_email_view, name='confirm-email'),
    url(r'^email-confirmed/$', static_page_view, name='email-confirmed',
        kwargs={'template': 'accounts/email_confirmed.html'}),

    url(r'^change-password/$', 'django.contrib.auth.views.password_change', name='password_change'),
    url(r'^recovery-email-sent/$', static_page_view, name='recovery-email-sent',
        kwargs={'template': 'accounts/recovery_email_sent.html'}),

    url(r'^user/(?P<pk>\d*)/approve/$', approve_user_view, name='approve-user'),

    url(r'^users/$', UserList.as_view(), name='user-list'),
    url(r'^user/(?P<pk>\d*)/edit/$', UserUpdate.as_view(), name='user-edit'),

    url(r'^datasets/$', DatasetList.as_view(), name='dataset-list'),
    url(r'^datasets/new/$', dataset_create_view, name='dataset-new'),
    url(r'^datasets/(?P<pk>\d*)/$', DatasetDetail.as_view(), name='dataset-detail'),
    url(r'^datasets/(?P<pk>\d*)/download/(?P<file_format>\w*)/$', dataset_download_view, name='dataset-download'),
    url(r'^datasets/(?P<pk>\d*)/edit/$', dataset_update_view, name='dataset-update'),
    url(r'^datasets/(?P<pk>\d*)/delete/$', DatasetDelete.as_view(), name='dataset-delete'),

    url(r'^components/$', ComponentList.as_view(), name='component-list'),
    url(r'^components/new/$', ComponentCreate.as_view(), name='component-new'),
    url(r'^components/(?P<pk>\d*)/edit/$', ComponentUpdate.as_view(), name='component-update'),
    url(r'^components/(?P<pk>\d*)/delete/$', ComponentDelete.as_view(), name='component-delete'),

    url(r'^experiments/$', ExperimentList.as_view(), name='experiment-list'),
    url(r'^experiments/new/$', ExperimentCreate.as_view(), name='experiment-new'),
    url(r'^experiments/(?P<pk>\d*)/edit/$', ExperimentCreate.as_view(), name='experiment-update'),
    url(r'^experiments/(?P<pk>\d*)/delete/$', ExperimentDelete.as_view(), name='experiment-delete'),

    url(r'^experiments/(?P<pk>\d*)/confirm/$', ExperimentDetail.as_view(), name='experiment-confirm'),

    # Dynamic urls
    url(r'^x/component-parameter-form/$', component_parameter_form, name='parameters-form'),
    url(r'^x/gen-parameter-prefixes/$', gen_parameter_prefixes, name='gen-parameter-prefixes'),
    # Dynamic component forms
    url(r'^x/upload_file_form/$', upload_file_form_view, name='component-upload-file-form'),
    url(r'^x/existing_file_form/$', ExistingFileView.as_view(), name='component-existing-file-form'),
    url(r'^x/midas_file_form/$', midas_file_form_view, name='component-midas-file-form'),
    url(r'^x/select_features_form/$', select_features_form_view, name='component-select-features-form'),
    url(r'^x/technical_details_form/$', technical_details_form_view, name='component-technical-details-form'),
    url(r'^x/chart_form/$', chart_form_view, name='component-chart-form'),
    url(r'^x/matrix_form/$', matrix_form_view, name='component-matrix-form'),
)

urlpatterns += staticfiles_urlpatterns()
urlpatterns += patterns('',
    (r'^media/(?P<path>.*)$', 'django.views.static.serve',
     {'document_root': settings.MEDIA_ROOT}),
)
