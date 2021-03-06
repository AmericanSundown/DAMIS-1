#! coding: utf-8

import arff
import csv
import tempfile
import StringIO
import zipfile
from datetime import datetime

from django import forms
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db.models import Q
from django.forms.util import ErrorList
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
User = get_user_model()
from django.utils.http import base36_to_int
from django.contrib.auth.tokens import default_token_generator
from damis.utils import save_task

from damis.models import Component
from damis.models import Connection
from damis.models import Dataset
from damis.models import DamisUser
from damis.models import Parameter
from damis.models import ParameterValue
from damis.models import Experiment
from damis.models import WorkflowTask

from django.forms.models import inlineformset_factory, BaseInlineFormSet
from django.forms.formsets import DELETION_FIELD_NAME

from damis.utils import slugify

VALIDATOR_FIELDS = {
    'dataset': {'class': forms.CharField,
        'attrs': {
            'required': False,
        }
    },
    'int': {'class': forms.IntegerField, 'attrs': {'required': False}},
    'string': {'class': forms.CharField, 'attrs': {'required': False}},
    'text': {'class': forms.CharField,
        'attrs': {
            'required': False,
        }
    },
    'boolean': {'class': forms.BooleanField, 'attrs': {'required': False}},
    'date': {'class': forms.DateField, 'attrs': {'required': False}},
    'datetime': {'class': forms.DateTimeField, 'attrs': {'required': False}},
    'time': {'class': forms.CharField, 'attrs': {'required': False}},
    'float': {'class': forms.FloatField, 'attrs': {'required': False}},
    'double': {'class': forms.FloatField, 'attrs': {'required': False}},
}


class DatasetForm(forms.ModelForm):
    file = forms.FileField(label=_('File'), required=False, widget=forms.FileInput())
    ## XXX: Firefox does not recognize mime types for 'tab' and 'arff'
    # csv: text/csv; tab: text/tab-separated-values; txt: text/plain;
    # arff: text/arff; zip: application/zip; xls: application/vnd.ms-excel
    # 'accept': 'text/csv,text/tab-separated-values,text/plain,text/arff,application/zip'
    user = forms.CharField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = Dataset
        fields = ('title', 'file', 'description', 'user')

    def __init__(self, user, *args, **kwargs):
        super(DatasetForm, self).__init__(*args, **kwargs)
        self.user = user

    def extract_file(self, archive):
        '''Extracts a compressed file from a zip archive.
        Throws an validation error when a file is corrupt or does not contain exactly one file.

        archive - the zip archive (InMemoryUploadedFile)
        '''
        try:
            zip_file = zipfile.ZipFile(archive)
        except zipfile.error:
            raise forms.ValidationError(_('Corrupted zip archive file.'))

        if not zip_file.testzip():
            file_list = zip_file.infolist()
            if len(file_list) == 1:
                compressed_file = file_list[0]
                content = zip_file.read(file_list[0])
                buff= StringIO.StringIO(content)
                uncompressed_file = InMemoryUploadedFile(buff, 'file', compressed_file.filename, None, buff.tell(), None)
            else:
                raise forms.ValidationError(_('The zip archive should contain exactly one file, {0} found.').format(len(file_list)))
        else:
            raise forms.ValidationError(_('Corrupted zip archive file.'))
        zip_file.close()
        return uncompressed_file

    def clean_file(self, *args, **kwargs):
        '''Converts the uploaded file to the arff file format, if possible.
        csv, txt and tab files are parsed as csv files with comma, comma and tab delimiter respectively.
        arff files are parsed and valid headers are recreated for them.
        zip files are checked to be valid and contain a single file; 
        the file is extracted and handled as other uncompressed types.
        '''
        input_file = self.cleaned_data.get('file')
        if not input_file:
            if self.instance and self.instance.file:
                return input_file
            else:
                raise forms.ValidationError(_("This field is required"))
        else:
            if self.instance:
                self.instance.created = datetime.now()
        title = self.cleaned_data.get('title', "-")

        # determine file name and extension
        name_parts = input_file.name.split(".")
        extension = name_parts[-1]
        col_names = []

        if extension == "zip":
            uncompressed_file = self.extract_file(input_file)
            input_file = uncompressed_file
            name_parts = input_file.name.split(".")
            extension = name_parts[-1]

        if extension == 'csv' or extension == 'txt':
            reader_file = input_file
            csv_reader = csv.reader(reader_file, delimiter=',', quotechar='"')
        elif extension == "tab":
            reader_file = input_file 
            csv_reader = csv.reader(reader_file, delimiter='\t', quotechar='"')
        elif extension == "arff":
            # read arff data section and recreate header,
            # thus we obtain a valid header
            tmp = tempfile.NamedTemporaryFile()
            data_sec = False
            for row in input_file:
                if not row.startswith("%"):
                    if data_sec:
                        tmp.write(row)
                    else:
                        row_std = row.strip().lower()
                        if row_std.startswith("@data"):
                            data_sec = True
                        elif row_std.startswith("@attribute"):
                            col_names.append(row.split()[1]);
            tmp.seek(0)
            reader_file = tmp
            csv_reader = csv.reader(reader_file, delimiter=',', quotechar='"')
        else:
            raise forms.ValidationError(_('File type is not supported. Please select a tab, csv, txt, arff or zip file.'))

        # parse file field as a number when possible
        content = []
        for in_row in csv_reader:
            row = []
            for in_col in in_row:
                col = in_col
                try:
                    col = int(in_col)
                except ValueError:
                    try:
                        col = float(in_col)
                    except ValueError:
                        pass
                row.append(col)
            content.append(row)

        reader_file.close()

        # save content to a temporary file
        # in order to process by arff function
        f = tempfile.NamedTemporaryFile()
        if col_names:
            arff.dump(f.name, content, names=col_names, relation=title)
        else:
            arff.dump(f.name, content, relation=title)
        f.seek(0)

        # transfer resulting arff file to memory
        # in order to return to django
        buff= StringIO.StringIO(f.read())
        f.close()
        arff_file = InMemoryUploadedFile(buff, 'file', slugify(unicode(title)) + ".arff", None, buff.tell(), None)

        return arff_file

    def clean_title(self):
        title = self.cleaned_data.get("title")
        user = self.user
        if Dataset.objects.filter(~Q(pk=self.instance.pk), user=user, title=title).exists():
            raise forms.ValidationError(_("Please choose a unique title, as \"{0}\" already exists.").format(title))
        return title

    def clean_user(self):
        return self.user or None

class DatasetSelectForm(forms.Form):
    dataset = forms.ModelChoiceField(queryset=Dataset.objects.all())


class LoginForm(forms.Form):
    username = forms.CharField(label=_('Username'), max_length=100)
    password = forms.CharField(label=_('Password'), max_length=128,
                        widget=forms.PasswordInput(render_value=False))

    def clean(self):
        cleaned_data = super(LoginForm, self).clean()
        if self.errors:
            return cleaned_data

        user = authenticate(**cleaned_data)
        if not user:
            raise forms.ValidationError(_('Username or password is incorrect'))
        cleaned_data['user'] = user
        return cleaned_data

class RegistrationForm(forms.Form):
    username = forms.CharField(label=_('Username'), max_length=100,)
    password = forms.CharField(label=_('Password'), max_length=128,
                        widget=forms.PasswordInput(render_value=False))
    password_repeat = forms.CharField(label=_('Repeat Password'),
            max_length=128, widget=forms.PasswordInput(render_value=False))
    first_name = forms.CharField(label=_('First name'), max_length=100,)
    last_name = forms.CharField(label=_('Last name'), max_length=100,)
    email = forms.EmailField(label=_('E-mail'), max_length=100)
    organization = forms.CharField(label=_('Organization'),
            widget=forms.Textarea(attrs={'rows':'5', 'cols': '25'}),
            required=False)

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(_('This username is already taken.'))
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(_('User with this email already exist.'))
        return email

    def is_valid(self):
        valid = super(RegistrationForm, self).is_valid()
        if not valid:
            return valid

        first_password = self.cleaned_data.get('password')
        repeat_password = self.cleaned_data.get('password_repeat')

        if first_password == repeat_password:
            return True
        errors = self._errors.setdefault('password_repeat', ErrorList())
        errors.append(u'Passwords do not match')
        return False

    def save(self):
        data = self.cleaned_data
        password = data.pop('password')
        data.pop('password_repeat')
        user = User.objects.create(**self.cleaned_data)
        user.set_password(password)
        user.save()
        return user

class ProfileForm(forms.ModelForm):
    class Meta:
        model = DamisUser
        fields = ['first_name', 'last_name', 'email', 'organization']


class EmailForm(forms.Form):
    email = forms.EmailField(label=_('E-mail'), max_length=100)

    def clean_email(self):
        email = self.cleaned_data['email']
        if not User.objects.filter(email=email, is_active=True).exists():
            raise forms.ValidationError(_('Please enter correct email address'))
        return email


class DataFileUploadForm(forms.Form):
    title = forms.CharField(label=_('Title'))
    data_file = forms.FileField(label=_('Dataset file'))
    comment = forms.CharField(label=_('Description'),
            widget=forms.Textarea(attrs={'rows':'5', 'cols': '25'}),
            required=False)


class ComponentForm(forms.ModelForm):
    class Meta:
        model = Component
        exclude = ['user']

class ParameterForm(forms.ModelForm):
    class Meta:
        model = Parameter
        fields = ['name', 'type', 'connection_type', 'required', 'default',
                  'label', 'description', 'label_lt', 'description_lt']

ParameterFormset = inlineformset_factory(Component, Parameter, extra=1, form=ParameterForm, can_delete=False)


class ExperimentForm(forms.ModelForm):
    workflow_state = forms.CharField(widget=forms.HiddenInput(), required=False)
    skip_validation = forms.CharField(widget=forms.HiddenInput(), required=False)

    def __init__(self, *args, **kwargs):
        super(ExperimentForm, self).__init__(*args, **kwargs)
        if not self.prefix:
            self.prefix = 'experiment'

    class Meta:
        model = Experiment
        exclude = ['user', 'start', 'finish', 'status']


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'is_active']


class ParameterValueForm(forms.ModelForm):
    parameter = forms.ModelChoiceField(queryset=Parameter.objects.all(),
                                       widget=forms.HiddenInput())
    source_ref = forms.CharField(max_length=255, widget=forms.HiddenInput(), required=False)

    class Meta:
        model = ParameterValue

    def __init__(self, *args, **kwargs):
        super(ParameterValueForm, self).__init__(*args, **kwargs)
        parameter = None
        if self.instance is not None and self.instance.pk:
            parameter = self.instance.parameter
        elif kwargs.get('instance'):
            parameter = kwargs['instance'].parameter
        elif self.data:
            parameter_id = self.data.get(self.prefix + '-parameter')
            if parameter_id:
                parameter = Parameter.objects.get(pk=parameter_id)

        if parameter:
            field_class = VALIDATOR_FIELDS[parameter.type]['class']
            field_attrs = VALIDATOR_FIELDS[parameter.type]['attrs']
            self.fields['value'] = field_class(**field_attrs)
            self.fields['value'].label = str(parameter)
            self.initial.update({'parameter': parameter, 'value': parameter.default})
            if self.instance:
                self.initial['value'] = self.instance.value

        if self.instance and self.instance.target.all():
            source = self.instance.target.all()[0].source
            pks = source.task.component.parameters.values_list('pk', flat=True)
            index = tuple(pks).index(source.parameter.pk)
            self.initial.update({'source_ref': 'PV_PK%s-%s-value' % (source.task.pk, index)})

    def is_valid(self):
        valid = super(ParameterValueForm, self).is_valid()
        if not valid:
            return valid

        value = self.cleaned_data.get('value')
        source_ref = self.cleaned_data.get('source_ref')
        if value or source_ref:
            return True

        parameter = self.cleaned_data.get('parameter')
        if parameter and parameter.required and not value:
            if parameter.connection_type == 'INPUT_CONNECTION':
                raise forms.ValidationError(_('Input connection is not connected'))
            else:
                errors = self._errors.setdefault('value', ErrorList())
                errors.append(_(u'This value must be specified'))
            return False

        if parameter and parameter.connection_type in ['INPUT_COMMON',
                                        'OUTPUT_VALUE', 'OUTPUT_CONNECTION']:
            return True
        return True

    def source_ref_to_obj(self, pv_prefix_to_obj):
        source_ref = self.cleaned_data['source_ref']
        if source_ref:
            obj = pv_prefix_to_obj[source_ref.split('-value')[0]]
            self.instance.source = obj
            self.instance.save()



ParameterValueFormset = inlineformset_factory(WorkflowTask, ParameterValue,
                            form=ParameterValueForm, extra=0, can_delete=False)

class BaseWorkflowTaskFormset(BaseInlineFormSet):
    def add_fields(self, form, index):
        super(BaseWorkflowTaskFormset, self).add_fields(form, index)

        # Create the nested formset
        try:
            instance = self.get_queryset()[index]
            pk_value = instance.pk
            pv_prefix = 'PV_PK%s' % pk_value
        except IndexError:
            instance = None
            pk_value = hash(form.prefix)
            pv_prefix = 'PV_%s' % pk_value

        data = self.data if self.data and index is not None else None
        # Do not create PV formset if post data do not contain any elems with
        # pv_value prefix.
        if data and not [a for a in data.keys() if pv_prefix in a]:
            form.parameter_values = []
            return

        form.parameter_values = [ParameterValueFormset(data=data,
                                                      instance=instance,
                                                      prefix=pv_prefix)]

    def is_valid(self):
        result = super(BaseWorkflowTaskFormset, self).is_valid()
        for form in self.forms:
            if hasattr(form, 'parameter_values'):
                for pv_form in form.parameter_values:
                    try:
                        result = result and pv_form.is_valid()
                    except forms.ValidationError, e:
                        errors = form._errors.setdefault('__all__', ErrorList())
                        errors.append(e.messages[0])
                        result = False
        return result


    def save_new(self, form, commit=True):
        """Saves and returns a new model instance for the given form."""
        instance = super(BaseWorkflowTaskFormset, self).save_new(form, commit=commit)

        form.instance = instance

        for pv in form.parameter_values:
            pv.instance = instance

            for cd in pv.cleaned_data:
                cd[pv.fk.name] = instance

        return instance

    def save_all(self, experiment=None, commit=True):
        if experiment:
            self.instance = experiment

        sources = save_task(experiment, self)

        for task_form in self.forms:
            for pv_form in task_form.parameter_values[0].forms:
                source_ref = pv_form.cleaned_data['source_ref']
                if source_ref:
                    source_ref = source_ref.split('-value')[0]
                    source = sources[source_ref]
                    target = pv_form.instance
                    exist = Connection.objects.filter(target=target, source=source)
                    if not exist:
                        Connection.objects.create(target=target, source=source)


    def should_delete(self, form):
        if self.can_delete:
            raw_delete_value = form._raw_value(DELETION_FIELD_NAME)
            should_delete = form.fields[DELETION_FIELD_NAME].clean(raw_delete_value)
            return should_delete
        return False


class WorkflowTaskForm(forms.ModelForm):
    class Meta:
        model = WorkflowTask
        exclude = ['stdout', 'stderr', 'processors', 'sequence', 'status']

WorkflowTaskFormset = inlineformset_factory(Experiment, WorkflowTask,
        formset=BaseWorkflowTaskFormset, form=WorkflowTaskForm, extra=0,
        can_delete=True)
CreateExperimentFormset = inlineformset_factory(Experiment, WorkflowTask,
        formset=BaseWorkflowTaskFormset, form=WorkflowTaskForm, extra=1,
        can_delete=True)


class PasswordRecoveryForm(forms.Form):
    password = forms.CharField(label=_('Password'), max_length=128,
                        widget=forms.PasswordInput(render_value=False))
    password_repeat = forms.CharField(label=_('Repeat Password'),
            max_length=128, widget=forms.PasswordInput(render_value=False))

    def is_valid(self):
        valid = super(PasswordRecoveryForm, self).is_valid()
        if not valid:
            return valid

        first_password = self.cleaned_data.get('password')
        repeat_password = self.cleaned_data.get('password_repeat')

        if first_password == repeat_password:
            return True
        errors = self._errors.setdefault('password_repeat', ErrorList())
        errors.append(u'Passwords do not match')
        return False

    def save(self, uidb36, token):
        password = self.cleaned_data.get('password')
        user = User.objects.get(pk=base36_to_int(uidb36))
        if default_token_generator.check_token(user, token):
            user.set_password(password)
            user.save()
        return user
