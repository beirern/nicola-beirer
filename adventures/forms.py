"""Wagtail forms for grouping existing recordings and uploading new legs."""

import logging

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.models import ReferenceIndex

from adventures.models import Route

logger = logging.getLogger(__name__)


class RouteLegForm(forms.Form):
    route = forms.ModelChoiceField(
        queryset=Route.objects.none(), required=False, label='Existing recording'
    )
    name = forms.CharField(max_length=255, required=False, label='New leg name')
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'rows': 2})
    )
    activity_type = forms.ChoiceField(
        choices=[('', 'Choose activity')] + list(Route.ActivityType.choices),
        required=False,
    )
    file = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(['gpx', 'fit'])],
        label='GPX or FIT file',
    )

    def __init__(self, *args, group=None, **kwargs):
        super().__init__(*args, **kwargs)
        available = Route.objects.filter(kind=Route.Kind.RECORDING).filter(
            models.Q(parent_route__isnull=True)
            | models.Q(parent_route_id=group.pk if group else None)
        )
        self.fields['route'].queryset = available.select_related('parent_route')

    def clean(self):
        data = super().clean()
        if data.get('route'):
            if (
                data.get('file')
                or data.get('name')
                or data.get('activity_type')
                or data.get('description')
            ):
                raise ValidationError(
                    'Choose an existing recording or upload a new leg, rather than both.'
                )
        else:
            for field in ('name', 'activity_type', 'file'):
                if not data.get(field):
                    self.add_error(field, 'Required when uploading a new leg.')
            if not self.errors:
                recording = Route(
                    name=data['name'],
                    description=data.get('description', ''),
                    activity_type=data['activity_type'],
                    file=data['file'],
                )
                try:
                    recording.full_clean()
                except ValidationError as exc:
                    for field, errors in exc.message_dict.items():
                        self.add_error(field if field in self.fields else None, errors)
                self.recording = recording
        return data


class BaseLegFormSet(forms.BaseFormSet):
    ordering_widget = forms.HiddenInput

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        selected = [
            form.cleaned_data['route'].pk
            for form in self.forms
            if form.cleaned_data
            and not form.cleaned_data.get('DELETE')
            and form.cleaned_data.get('route')
        ]
        if len(selected) != len(set(selected)):
            raise ValidationError('A recording can appear only once in a group.')


LegFormSet = forms.formset_factory(
    RouteLegForm,
    formset=BaseLegFormSet,
    extra=0,
    can_order=True,
    can_delete=True,
    max_num=500,
    validate_max=True,
)


class RouteAdminForm(WagtailAdminModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound and 'kind' not in self.data:
            self.data = self.data.copy()
            self.data['kind'] = self.instance.kind
        self.route_kind = (
            self.data.get('kind', self.instance.kind)
            if self.is_bound
            else self.instance.kind
        )
        self.fields['file'].required = self.route_kind == Route.Kind.RECORDING
        self.fields['file'].widget.attrs['data-has-recording'] = (
            'true' if self.instance.file else 'false'
        )
        self.fields['activity_type'].required = self.route_kind == Route.Kind.RECORDING
        children = (
            self.instance.children.order_by('position', 'pk')
            if self.instance.pk
            else []
        )
        initial = [{'route': child.pk, 'ORDER': child.position} for child in children]
        self.legs = LegFormSet(
            self.data if self.is_bound else None,
            self.files if self.is_bound else None,
            initial=initial,
            prefix='legs',
            form_kwargs={'group': self.instance},
        )

    def _update_errors(self, errors):
        # Parent assignment is managed by the group's leg list, not a child field.
        if hasattr(errors, 'error_dict'):
            remapped = {}
            for key, values in errors.error_dict.items():
                remapped.setdefault(
                    key if key in self.fields else NON_FIELD_ERRORS, []
                ).extend(values)
            errors = ValidationError(remapped)
        return super()._update_errors(errors)

    def clean(self):
        data = super().clean()
        if data.get('kind') == Route.Kind.GROUP:
            data['activity_type'] = ''
            if not self.legs.is_valid():
                self.add_error(None, 'Check the legs below.')
            elif self.for_user:
                rows = self.legs.ordered_forms
                selected = {
                    form.cleaned_data['route'].pk
                    for form in rows
                    if form.cleaned_data.get('route')
                }
                existing = (
                    set(self.instance.children.values_list('pk', flat=True))
                    if self.instance.pk
                    else set()
                )
                if (selected or existing) and not self.for_user.has_perm(
                    'adventures.change_route'
                ):
                    self.add_error(
                        None,
                        'You need permission to change routes to manage existing legs.',
                    )
                if any(
                    not form.cleaned_data.get('route') for form in rows
                ) and not self.for_user.has_perm('adventures.add_route'):
                    self.add_error(
                        None, 'You need permission to add routes to upload new legs.'
                    )
        return data

    @property
    def media(self):
        return (
            super().media
            + self.legs.media
            + forms.Media(js=['adventures/route-editor.js'])
        )

    def is_multipart(self):
        return True

    def has_changed(self):
        return super().has_changed() or (
            self.route_kind == Route.Kind.GROUP and self.legs.has_changed()
        )

    def _save_legs(self):
        if self.instance.kind != Route.Kind.GROUP:
            return
        forms_to_save = self.legs.ordered_forms
        ids = [
            form.cleaned_data['route'].pk
            for form in forms_to_save
            if form.cleaned_data.get('route')
        ]
        locked = {
            route.pk: route
            for route in Route.objects.select_for_update()
            .filter(
                models.Q(pk__in=ids)
                | models.Q(parent_route=self.instance)
                | models.Q(pk=self.instance.pk)
            )
            .order_by('pk')
        }
        for pk in ids:
            if (
                pk not in locked
                or locked[pk].kind != Route.Kind.RECORDING
                or locked[pk].parent_route_id not in (None, self.instance.pk)
            ):
                raise ValidationError(
                    'A selected recording now belongs to another group. Reload and choose an ungrouped recording.'
                )
        detached = [
            route
            for route in locked.values()
            if route.parent_route_id == self.instance.pk and route.pk not in ids
        ]
        Route.objects.filter(parent_route=self.instance).exclude(pk__in=ids).update(
            parent_route=None, position=0
        )
        for recording in detached:
            recording.parent_route = None
            recording.position = 0
            ReferenceIndex.create_or_update_for_object(recording)
        for position, form in enumerate(forms_to_save):
            existing = form.cleaned_data.get('route')
            recording = locked[existing.pk] if existing else form.recording
            recording.parent_route = self.instance
            recording.position = position
            recording.save()
        self.instance.__dict__.pop('recordings', None)
        self.instance._prefetched_objects_cache = {}

    def save(self, commit=True):
        with transaction.atomic():
            instance = super().save(commit=commit)
            if commit:
                self._save_legs()
                self._warm_after_commit()
            else:
                save_m2m = self.save_m2m

                def save_related():
                    with transaction.atomic():
                        save_m2m()
                        self._save_legs()
                        self._warm_after_commit()

                self.save_m2m = save_related
            return instance

    def _warm_after_commit(self):
        route_ids = {self.instance.pk, self.instance.parent_route_id} - {None}

        def warm():
            from adventures.map_cache import warm_route_overview

            for route_id in route_ids:
                try:
                    warm_route_overview(route_id)
                except Exception:
                    logger.exception('Could not warm map overview for route %s', route_id)

        transaction.on_commit(warm)
