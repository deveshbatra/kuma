"""Models for content moderation flagging"""
import logging

from django.db import models
from django.conf import settings
from django.db.models import F

from django.core import urlresolvers
from django.core.mail import send_mail

from django.contrib.sites.models import Site
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import User
from django.contrib.contenttypes import generic

from django.utils.translation import ugettext_lazy as _

from django.template import Context, loader

from devmo.models import UserProfile

from .utils import get_ip, get_unique


FLAG_REASONS = getattr(settings, "FLAG_REASONS", (
    ('notworking',    _('This is not working for me')),
    ('inappropriate', _('This contains inappropriate content')),
    ('plagarised',    _('This was not created by the author')),
    ('fakeauthor',    _('The author is fake')),
))

FLAG_STATUSES = getattr(settings, "FLAG_STATUSES", (
    ("flagged",  _("Flagged")),
    ("rejected", _("Flag rejected by moderator")),
    ("notified", _("Creator notified")),
    ("hidden",   _("Content hidden by moderator")),
    ("deleted",  _("Content deleted by moderator")),
))

FLAG_NOTIFICATIONS = dict([reason, True] for reason in FLAG_REASONS)
# to refine flag notifications, change preceding line to False and add
# individual reasons to the set like so:
#FLAG_NOTIFICATIONS['inappropriate'] = True

class ContentFlagManager(models.Manager):
    """Manager for ContentFlags"""

    def flag(self, request, object, flag_type, explanation, recipients=None):
        """Create a flag for a content item, if the unique request hasn't
        already done so before."""
        if flag_type not in dict(FLAG_REASONS):
            return (None, False)

        user, ip, user_agent, session_key = get_unique(request)

        content_type = ContentType.objects.get_for_model(object)

        cf = ContentFlag.objects.get_or_create(
                content_type=content_type, object_pk=object.pk,
                ip=ip, user_agent=user_agent, user=user, session_key=session_key,
                defaults=dict(flag_type=flag_type, explanation=explanation,))
        if recipients:
            subject = _("{object} Flagged")
            subject = subject.format(object=object)
            t = loader.get_template('contentflagging/email/flagged.ltxt')
            url = '/admin/contentflagging/contentflag/' + str(object.pk)
            host = Site.objects.get_current().domain
            content = t.render(Context({'url':url,'host':host,
                                        'object':object,'flag_type':flag_type}))
            send_mail(subject, content, settings.DEFAULT_FROM_EMAIL, recipients)
        return cf


class ContentFlag(models.Model):
    """Moderation flag submitted against a content item"""
    objects = ContentFlagManager()

    class Meta:
        ordering = ('-created',)
        get_latest_by = 'created'
        unique_together = (('content_type', 'object_pk',
            'ip', 'session_key', 'user_agent', 'user'),)

    flag_status = models.CharField(
            _('current status of flag review'),
            max_length=16, blank=False, choices=FLAG_STATUSES, default='flagged')
    flag_type = models.CharField(
            _('reason for flagging the content'),
            max_length=64, db_index=True, blank=False, choices=FLAG_REASONS)
    explanation = models.TextField(
            _('please explain what content you feel is inappropriate'),
            max_length=255, blank=True)
    content_type = models.ForeignKey(
            ContentType, editable=False,
            verbose_name="content type",
            related_name="content_type_set_for_%(class)s",)
    object_pk = models.CharField(
            _('object ID'),
            max_length=32, editable=False)
    content_object = generic.GenericForeignKey(
            'content_type', 'object_pk')

    ip = models.CharField(
            max_length=40, editable=False,
            blank=True, null=True)
    session_key = models.CharField(
            max_length=40, editable=False,
            blank=True, null=True)
    user_agent = models.CharField(
            max_length=128, editable=False,
            blank=True, null=True)
    user = models.ForeignKey(
            User, editable=False, blank=True, null=True)

    created = models.DateTimeField(
            _('date submitted'),
            auto_now_add=True, blank=False, editable=False)
    modified = models.DateTimeField(
            _('date last modified'),
            auto_now=True, blank=False)

    def __unicode__(self):
        return 'ContentFlag %(flag_type)s -> "%(title)s"' % dict(
                flag_type=self.flag_type, title=str(self.content_object))

    def content_view_link(self):
        """HTML link to the absolute URL for the linked content object"""
        object = self.content_object
        return ('<a target="_new" href="%(link)s">View %(title)s</a>' %
                dict(link=object.get_absolute_url(), title=object))

    content_view_link.allow_tags = True

    def content_admin_link(self):
        """HTML link to the admin page for the linked content object"""
        object = self.content_object
        ct = ContentType.objects.get_for_model(object)
        url_name = 'admin:%(app)s_%(model)s_change' % dict(
            app=ct.app_label, model=ct.model)
        link = urlresolvers.reverse(url_name, args=(object.id,))
        return ('<a target="_new" href="%(link)s">Edit %(title)s</a>' %
                dict(link=link, title=object))

    content_admin_link.allow_tags = True