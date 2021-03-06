#! coding: utf-8
import csv
import json
import re
import tempfile

from PIL import Image
from io import BytesIO
import cStringIO

from math import floor
from numpy import arange
from os.path import join, exists, getsize, splitext, split
from os import makedirs, listdir
from shutil import copy
from subprocess import call, Popen, PIPE

from collections import OrderedDict

from django.conf import settings
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth import get_user_model
User = get_user_model()
from django.core.urlresolvers import reverse_lazy
from django.core.context_processors import csrf
from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponseRedirect, HttpResponse, Http404
from django.shortcuts import render, get_object_or_404, render_to_response
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.utils.http import int_to_base36, base36_to_int
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ugettext
from django.forms.models import inlineformset_factory
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.views.decorators.csrf import csrf_exempt

from damis.settings import BUILDOUT_DIR
from damis.constants import COMPONENT_TITLE__TO__FORM_URL, FILE_TYPE__TO__MIME_TYPE
from damis.utils import slugify, strip_arff_header, save_task

from damis.forms import LoginForm, RegistrationForm, EmailForm, PasswordRecoveryForm
from damis.forms import DatasetForm
from damis.forms import ComponentForm
from damis.forms import ParameterForm, ParameterFormset
from damis.forms import ExperimentForm
from damis.forms import WorkflowTaskFormset, CreateExperimentFormset, ParameterValueFormset, ParameterValueForm
from damis.forms import DatasetSelectForm
from damis.forms import UserUpdateForm
from damis.forms import ProfileForm
from damis.forms import VALIDATOR_FIELDS

from damis.models import Component
from damis.models import Cluster
from damis.models import Connection
from damis.models import Parameter, ParameterValue
from damis.models import Dataset
from damis.models import Experiment
from damis.models import WorkflowTask


class LoginRequiredMixin(object):
    @method_decorator(login_required(login_url=reverse_lazy('login')))
    def dispatch(self, *args, **kwargs):
        return super(LoginRequiredMixin, self).dispatch(*args, **kwargs)

class SuperUserRequiredMixin(object):
    @method_decorator(login_required(login_url=reverse_lazy('login')))
    def dispatch(self, *args, **kwargs):
        user = self.request.user
        if not user.is_superuser:
            return HttpResponseRedirect(reverse_lazy('login'))
        return super(SuperUserRequiredMixin, self).dispatch(*args, **kwargs)

class ListDeleteMixin(object):
    success_url = reverse_lazy('home')

    def get_context_data(self, **kwargs):
        context = super(ListDeleteMixin, self).get_context_data(**kwargs)
        context['request'] = self.request
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        if action == 'delete':
            for pk in request.POST.getlist('pk'):
                obj = self.model.objects.get(pk=pk)
                obj.delete()
        return HttpResponseRedirect(self.success_url)

def index_view(request):
    return HttpResponseRedirect(reverse_lazy('experiment-new'))

def static_page_view(request, template):
    return render(request, template, {})

class DatasetList(ListDeleteMixin, LoginRequiredMixin, ListView):
    model = Dataset
    paginate_by = 25
    template_name = 'damis/dataset_list.html'
    success_url = reverse_lazy('dataset-list')

    def get_queryset(self):
        order_by = self.request.GET.get('order_by') or '-created'
        qs = super(DatasetList, self).get_queryset()
        qs = qs.filter(user__id=self.request.user.pk)
        if 'title' in order_by:
            qs = qs.extra(select={'title_lower': 'lower(title)'})
            order_by = order_by + '_lower'
        return qs.order_by(order_by)

class DatasetDetail(LoginRequiredMixin, DetailView):
    model = Dataset

class DatasetDelete(LoginRequiredMixin, DeleteView):
    model = Dataset
    success_url = reverse_lazy('dataset-list')

def dataset_download_view(request, pk, file_format):
    dataset = Dataset.objects.get(pk=pk)
    file = dataset.file
    response = HttpResponse(mimetype='text/csv')
    response['Content-Disposition'] = 'attachment; filename=%s.csv' % (file,)
    response.write(file.read())
    return response


class ComponentCreate(LoginRequiredMixin, CreateView):
    model = Component
    form_class = ComponentForm
    template_name = 'damis/component_form.html'

    def get(self, request, *args, **kwargs):
        self.object = None
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        parameter_form =  ParameterFormset()
        return self.render_to_response(
                self.get_context_data(form=form,
                    parameter_form=parameter_form))

    def post(self, request, *args, **kwargs):
        self.object = None
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        parameter_form = ParameterFormset(self.request.POST)
        if form.is_valid() and parameter_form.is_valid():
            return self.form_valid(form, parameter_form)
        else:
            return self.form_invalid(form, parameter_form)

    def form_valid(self, form, parameter_form):
        self.object = form.save()
        parameter_form.instance = self.object
        parameter_form.save()
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form, parameter_form):
        return self.render_to_response(self.get_context_data(form=form,
            parameter_form=parameter_form))


class ComponentList(ListDeleteMixin, LoginRequiredMixin, ListView):
    model = Component
    template_name = 'damis/component_list.html'
    paginate_by = 25
    success_url = reverse_lazy('component-list')

    def get_queryset(self):
        order_by = self.request.GET.get('order_by') or '-created'
        qs = super(ComponentList, self).get_queryset()
        return qs.order_by(order_by)


class UserList(ListDeleteMixin, SuperUserRequiredMixin, ListView):
    model = User
    template_name = 'damis/user_list.html'
    paginate_by = 25
    success_url = reverse_lazy('user-list')


class UserUpdate(LoginRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'damis/user_update.html'

    def form_valid(self, form):
        user = User.objects.get(pk=form.instance.pk)
        activate = form.cleaned_data.get('is_active')
        if user and not user.is_active and activate:
            user.activate(domain=self.request.get_host())
        return super(UserUpdate, self).form_valid(form)

    def get_success_url(self):
        return reverse_lazy('user-list')


class ComponentUpdate(LoginRequiredMixin, UpdateView):
    model = Component
    form_class = ComponentForm
    template_name = 'damis/component_form.html'

    def post(self, request, *args, **kwargs):
        self.object = Component.objects.get(pk=self.kwargs['pk'])
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        parameter_form = ParameterFormset(self.request.POST, instance=self.object)
        if form.is_valid() and parameter_form.is_valid():
            return self.form_valid(form, parameter_form)
        else:
            return self.form_invalid(form, parameter_form)

    def form_valid(self, form, parameter_form):
        self.object = form.save()
        parameter_form.instance = self.object
        parameter_form.save()
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form, parameter_form):
        return self.render_to_response(self.get_context_data(form=form,
            parameter_form=parameter_form))

    def get_context_data(self, **kwargs):
        context = super(ComponentUpdate, self).get_context_data(**kwargs)
        ParameterFormset = inlineformset_factory(Component, Parameter, extra=0, can_delete=True)
        context['parameter_form'] = ParameterFormset(instance=self.object)
        return context

class ComponentDetail(LoginRequiredMixin, DetailView):
    model = Component

class ComponentDelete(LoginRequiredMixin, DeleteView):
    model = Component
    success_url = reverse_lazy('component-list')


class ExperimentList(ListDeleteMixin, LoginRequiredMixin, ListView):
    model = Experiment
    paginate_by = 25
    success_url = reverse_lazy('experiment-list')

    def get_queryset(self):
        qs = super(ExperimentList, self).get_queryset()
        return qs.order_by('-created')


class ExperimentDetail(LoginRequiredMixin, DetailView):
    model = Experiment

class ExperimentDelete(LoginRequiredMixin, DeleteView):
    model = Experiment
    success_url = reverse_lazy('experiment-list')

class ExperimentUpdate(LoginRequiredMixin, UpdateView):
    model = Experiment

    def get(self, request, *args, **kwargs):
        self.object = None
        experiment = get_object_or_404(Experiment, pk=self.kwargs['pk'])
        task_formset = WorkflowTaskFormset(instance=experiment)
        return self.render_to_response(self.get_context_data(
                    experiment=task_formset.instance,
                    task_formset=task_formset,
                ))

    def post(self, request, *args, **kwargs):
        self.object = None
        instance = Experiment.objects.get(pk=self.kwargs['pk'])

        task_formset = WorkflowTaskFormset(self.request.POST,
                                           instance=instance)
        if task_formset.is_valid():
            return self.form_valid(task_formset)
        else:
            return self.form_invalid(task_formset)

    def form_valid(self, task_formset):
        self.object = task_formset.save_all()
        return HttpResponseRedirect(reverse_lazy('experiment-list'))

    def form_invalid(self, task_formset):
        return self.render_to_response(self.get_context_data(
                        experiment=task_formset.instance,
                        task_formset=task_formset,
                    ))


class ExperimentCreate(LoginRequiredMixin, CreateView):
    model = Experiment
    template_name = 'damis/experiment_create.html'

    def get(self, request, *args, **kwargs):
        self.object = None

        experiment_pk = self.kwargs.get('pk')
        if experiment_pk:
            experiment = Experiment.objects.get(pk=experiment_pk)
        else:
            experiment = Experiment()

        experiment_form = ExperimentForm(instance=experiment)
        task_formset = CreateExperimentFormset(instance=experiment)

        # Move one extra empty task formset to the begining of forms
        form_count = len(task_formset.forms)
        task_formset.forms.insert(0, task_formset.forms.pop(form_count - 1))

        return self.render_to_response(self.get_context_data(
                    experiment=task_formset.instance,
                    task_formset=task_formset,
                    experiment_form=experiment_form,
                ))

    def get_context_data(self, **kwargs):
        context = super(ExperimentCreate, self).get_context_data(**kwargs)
        context['dataset_form'] = DatasetSelectForm()
        context.update(csrf(self.request))

        # assign component to clusters by category
        components = Component.objects.all()
        clusters = dict()
        for component in components:
            if not component.cluster in clusters:
                clusters[component.cluster] = dict()
            cat_name = component.get_category_display()
            if not cat_name in clusters[component.cluster]:
                clusters[component.cluster][cat_name] = []
            clusters[component.cluster][cat_name].append(component)

        # sort components by clusters and categories
        all_clusters = Cluster.objects.all()
        sorted_clusters = []
        for cluster in all_clusters:
            b = []
            for cat, cat_name in Component.CATEGORIES:
                if cluster in clusters and cat_name in clusters[cluster]:
                    b.append([cat_name, clusters[cluster][cat_name]]);
            a = [cluster, b]
            sorted_clusters.append(a);

        context['clusters'] = sorted_clusters
        context['component_form_urls'] = COMPONENT_TITLE__TO__FORM_URL.items()
        context['component_details'] = [[c.pk, {"title": c.title, "label": c.get_label_display(), "cluster_ico": c.cluster.icon.url, "ico": c.icon.url}] for c in Component.objects.all()]
        return context

    def skip_validation(self, experiment_form, task_formset):
        experiment_form.full_clean()
        exp_data = experiment_form.cleaned_data
        exp_data.pop('skip_validation')
        if experiment_form.instance and experiment_form.instance.pk:
            exp = experiment_form.instance
            experiment_form.save()
        else:
            exp = Experiment.objects.create(**exp_data)

        task_formset.full_clean()
        for task_form in task_formset.forms:
            for pv_formset in task_form.parameter_values:
                pv_formset.full_clean()

        sources = save_task(exp, task_formset)

        for task_form in task_formset.forms:
            for pv_form in task_form.parameter_values[0].forms:
                source_ref = pv_form.cleaned_data['source_ref']
                if source_ref:
                    source_ref = source_ref.split('-value')[0]
                    source = sources[source_ref]
                    target = pv_form.instance
                    exist = Connection.objects.filter(target=target, source=source)
                    if not exist:
                        Connection.objects.create(target=target, source=source)

        return HttpResponse(reverse_lazy('experiment-update', kwargs={'pk': exp.pk}))

    def post(self, request, *args, **kwargs):
        self.object = None

        experiment_pk = self.kwargs.get('pk')
        if experiment_pk:
            experiment = Experiment.objects.get(pk=experiment_pk)
        else:
            experiment = Experiment()

        experiment_form = ExperimentForm(self.request.POST, instance=experiment)
        task_formset = CreateExperimentFormset(self.request.POST, instance=experiment)

        if self.request.POST.get(experiment_form.prefix + '-skip_validation'):
            return self.skip_validation(experiment_form, task_formset)

        if experiment_form.is_valid() and task_formset.is_valid():
            return self.form_valid(experiment_form, task_formset)
        else:
            return self.form_invalid(experiment_form, task_formset)

    def form_valid(self, experiment_form, task_formset):
        exp = experiment_form.save()
        self.object = task_formset.save_all(experiment=exp)

        command = '{0}/bin/python {0}/src/damis/run_experiment.py {1}'.format(BUILDOUT_DIR, exp.pk)
        response = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
        # response.wait()
        # response.communicate()
        exp.status = 'RUNNING'
        exp.save()
        return HttpResponse(reverse_lazy('experiment-list'))

    def form_invalid(self, experiment_form, task_formset):
        return render_to_response('damis/_experiment_form.html',
                        self.get_context_data(
                            experiment=task_formset.instance,
                            task_formset=task_formset,
                            experiment_form=experiment_form,
                        ))


@login_required(login_url=reverse_lazy('login'))
def gen_parameter_prefixes(request):
    prefixes = request.GET.getlist('prefixes[]')
    task_ids = request.GET.getlist('taskIds[]')
    task_prefixes = [re.findall('(tasks-\d+)', prefix)[0] for prefix in prefixes]
    pv_prefixes = []
    for task_id, task_prefix in zip(task_ids, task_prefixes):
        if task_id and task_id != '-':
            pv_prefixes.append('PV_PK%s' % (task_id,))
        else:
            pv_prefixes.append('PV_%s' % (str(hash(task_prefix)),))
    return HttpResponse(",".join(pv_prefixes))

@login_required(login_url=reverse_lazy('login'))
def component_parameter_form(request):
    component = get_object_or_404(Component, pk=request.GET.get('component_id'))
    task_form_prefix = re.findall('[id_]*(\w+-\d+)', request.GET.get('prefix'))[0]
    prefix = 'PV_%s' % hash(task_form_prefix)

    val_params = component.parameters.filter(Q(connection_type="INPUT_VALUE")|Q(connection_type="INPUT_CONNECTION")|Q(connection_type="OUTPUT_CONNECTION"))
    ParameterValueFormset = inlineformset_factory(WorkflowTask,
                                ParameterValue,
                                form=ParameterValueForm,
                                extra=len(val_params),
                                can_delete=False
                            )
    parameter_formset = ParameterValueFormset(instance=None, prefix=prefix)
    for parameter, form in zip(val_params, parameter_formset.forms):
        field_class = VALIDATOR_FIELDS[parameter.type]['class']
        field_attrs = VALIDATOR_FIELDS[parameter.type]['attrs']
        form.fields['value'] = field_class(**field_attrs)
        form.fields['value'].label = str(parameter)
        form.initial.update({'parameter': parameter, 'value': parameter.default})
        if form.instance and form.instance.value:
            form.initial['value'] = form.instance.value

    return render_to_response('damis/_parameter_formset.html', {
        'formset': parameter_formset,
        })

@login_required(login_url=reverse_lazy('login'))
def dataset_create_view(request):
    context = csrf(request)
    if request.method == 'POST':
        form = DatasetForm(data=request.POST, files=request.FILES, user=request.user)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse_lazy('dataset-list'))
    else:
        form = DatasetForm(user=request.user)
    context['form'] = form
    context['user'] = request.user
    return render_to_response('damis/dataset_new.html', context)

@login_required(login_url=reverse_lazy('login'))
def dataset_update_view(request, pk):
    context = csrf(request)
    if request.method == 'POST':
        form = DatasetForm(data=request.POST, files=request.FILES, user=request.user)
        form.instance = Dataset.objects.get(pk=pk)
        if form.is_valid():
            form.save()
    else:
        form = DatasetForm(instance=Dataset.objects.get(pk=pk), user=request.user)
    context['form'] = form

    return render_to_response('damis/_dataset_update.html', context)

@login_required(login_url=reverse_lazy('login'))
def upload_file_form_view(request):
    '''Handles Ajax request to update the uploaded file component.

    request - Ajax request. Fields:
        dataset_url - url of the uploaded data file, currently used by the component.
    '''
    context = csrf(request)
    if request.method == 'POST':
        dataset_url = request.POST.get("dataset_url")
        form = DatasetForm(data=request.POST, files=request.FILES, user=request.user)
        if form.is_valid():
            dataset = form.save()
            context['file_path'] = dataset.file.url
            context['file_name'] = dataset.title
            context['new_file_path'] = dataset.file.url

            # clear the form
            form = DatasetForm(user=request.user)
        else:
            context['file_path'] = dataset_url
    else:
        context['GET'] = True
        dataset_url = request.GET.get("dataset_url")
        if dataset_url:
            context['file_path'] = dataset_url
            file_name = split(dataset_url)[1]
            file_pattern = "{0}/datasets/{1}".format(request.user.username, file_name)
            dataset = Dataset.objects.get(file=file_pattern)
            context['file_name'] = dataset.title
        form = DatasetForm(user=request.user)
    context['form'] = form

    return render_to_response('damis/_dataset_form.html', context)


class ExistingFileView(LoginRequiredMixin, ListView):
    model = Dataset
    paginate_by = 10
    template_name = 'damis/_existing_file.html'
    success_url = reverse_lazy('dataset-list')

    def get_page_no(self, ds):
        index = self.get_queryset().filter(created__gt=ds.created).count()
        return index / self.paginate_by + 1

    def get_queryset(self):
        order_by = self.request.GET.get('order_by') or '-created'
        qs = super(ExistingFileView, self).get_queryset()
        qs = qs.filter(user__id=self.request.user.pk)
        if 'title' in order_by:
            qs = qs.extra(select={'title_lower': 'lower(title)'})
            order_by = order_by + '_lower'
        return qs.order_by(order_by)

    def get_context_data(self, **kwargs):
        context = {'request': self.request}
        if self.request.GET.has_key('dataset_url'):
            dataset_url = self.request.GET.get('dataset_url')
            context['file_path'] = dataset_url
            file_name = split(dataset_url)[1]
            file_pattern = "{0}/datasets/{1}".format(self.request.user.username, file_name)
            dataset = Dataset.objects.get(file=file_pattern)
            context['file_name'] = dataset.title
            context['highlight_pk'] = dataset.pk

            if not self.request.GET.has_key('page') and \
               not self.request.GET.has_key('order_by'):
                self.kwargs['page'] = self.get_page_no(dataset)
            self.request.GET = self.request.GET.copy()
            self.request.GET.pop('dataset_url')

        context.update(super(ExistingFileView, self).get_context_data(**kwargs))
        return context


@login_required(login_url=reverse_lazy('login'))
def midas_file_form_view(request):
    return HttpResponse(_('Not implemented, yet'))

@login_required(login_url=reverse_lazy('login'))
def select_features_form_view(request):
    return HttpResponse(_('Not implemented, yet'))

def file_to_table(file_url):
    '''Splits the file into header (rows) and content (structured as a matrix) portions.
    file_url - file path on the server
    '''
    f = open(BUILDOUT_DIR + '/var/www' + file_url)
    file_table = []
    header = [[_("Object No."), None]]
    data_sec = False
    count = 0
    for row in f:
        if data_sec:
            count += 1
            res_row = [count]
            res_row.extend([cell for cell in row.split(",")])
            file_table.append(res_row)
        else:
            row_std = row.strip().lower()
            if row_std.startswith("@data"):
                data_sec = True
            elif row_std.startswith("@attribute"):
                parts = row.split()
                col_name = parts[1]
                col_type = parts[2]
                attr_no = re.findall("^attr(\d+)$", col_name)
                if attr_no:
                    header.append([_("attr{0}").format(attr_no[0]), col_type])
                else:
                    header.append([col_name, col_type])
    f.close()
    return header, file_table

def convert(file_path, file_format):
    '''Opens, converts file to specified format and returns it.
    file_path - file path on the server 
    file_format - result file format, desired by the user
    '''
    f = open(BUILDOUT_DIR + '/var/www' + file_path)
    if file_format == "arff":
        return f
    elif file_format == "csv" or file_format == "tab" or file_format == "txt" or file_format == "xls" or file_format == "xlsx":
        # strip the header
        file_no_header = tempfile.NamedTemporaryFile()
        data_sec = False
        for row in f:
            if data_sec:
                file_no_header.write(row)
            else:
                row_std = row.strip().lower()
                if row_std.startswith("@data"):
                    data_sec = True
        file_no_header.seek(0)
        res = file_no_header

        if file_format == "tab":
            # read stripped file as csv
            csv_reader = csv.reader(file_no_header, delimiter=',', quotechar='"')
            file_res = tempfile.NamedTemporaryFile()
            # write file as csv with a specific delimiter
            csv_writer = csv.writer(file_res, delimiter='\t', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            for row in csv_reader:
                csv_writer.writerow(row)
            file_no_header.close()
            file_res.seek(0)
            res = file_res
        return res
    else:
        return f # default action - return arff

@login_required(login_url=reverse_lazy('login'))
def technical_details_form_view(request):
    '''Handles Ajax GET request to update the technical details component.

    request - Ajax GET request. Fields:
        pv_name - OUTPUT_CONNECTION parameter form input name; used to track down the task, output of which should be rendered by the technical details component
    '''
    pv_name = request.GET.get('pv_name')
    context = {}
    if pv_name and re.findall('PV_PK(\d+)-\d+-value', pv_name):
        task_pk = re.findall('PV_PK(\d+)-\d+-value', pv_name)[0]
        task = WorkflowTask.objects.get(pk=task_pk)
        params = task.parameter_values.filter(parameter__connection_type="OUTPUT_VALUE")
        context['values'] = params

    if not context.get('values'):
        return HttpResponse(_('You have to execute this experiment first to see the result.'))
    else:
        return render_to_response('damis/_technical_details.html', context)

def download_file(file_url, file_format):
    '''Prepares the HTTP response to download a file in a given format.

    file_url - url from which to download the file
    file_format - file download format
    '''
    filename = splitext(split(file_url)[1])[0]
    response = HttpResponse(mimetype=FILE_TYPE__TO__MIME_TYPE[file_format])
    response['Content-Disposition'] = 'attachment; filename=%s.%s' % (filename, file_format)
    converted_file = convert(file_url, file_format=file_format)
    response.write(converted_file.read())
    return response

@login_required(login_url=reverse_lazy('login'))
def matrix_form_view(request):
    '''Handles Ajax GET request to update the matrix view component.

    request - Ajax GET request. Fields:
        dataset_url - url of the data file, which is to be rendered ty the matrix view component
        download - if True return a downloadable file, else return HTML
        format - file format
    '''
    dataset_url = request.GET.get('dataset_url');
    context = {}
    if dataset_url:
        if request.GET.get('download'):
            return download_file(dataset_url, request.GET.get('format'))
        else:
            context['header'], context['file'] = file_to_table(dataset_url)
            return render_to_response('damis/_matrix_view.html', context)
    else:
        return HttpResponse(_('You have to execute this experiment first to see the result.'))

def read_classified_data(file_url, x, y, clsCol):
    f = open(BUILDOUT_DIR + '/var/www' + file_url)

    result = OrderedDict()
    minX = None; maxX = None
    minY = None; maxY = None
    minCls = None; maxCls = None
    clsType = None
    data_sec = False
    arff_cls = None # class attribute number
    attributes = []
    max_classes = 120
    error = None

    # first read
    for row in f:
        if data_sec:
            # analyse data portion of the file
            cells = row.rstrip().split(",")
            if minX is None or float(cells[x]) < minX:
                minX = float(cells[x])
            if maxX is None or float(cells[x]) > maxX:
                maxX = float(cells[x])
            if minY is None or float(cells[y]) < minY:
                minY = float(cells[y])
            if maxY is None or float(cells[y]) > maxY:
                maxY = float(cells[y])

            if clsType != "string":
                if minCls is None or float(cells[clsCol]) < minCls:
                    try:
                        minCls = int(cells[clsCol])
                    except ValueError:
                        minCls = float(cells[clsCol])
                if maxCls is None or float(cells[clsCol]) > maxCls:
                    try:
                        maxCls = int(cells[clsCol])
                    except ValueError:
                        maxCls = float(cells[clsCol])

            if not (clsType == "string" or clsType == "integer"):
                continue

            # try to classify only if the column is string
            # other types are classified during second read when min/max
            # are known
            cls = cells[clsCol]
            if not cls in result:
                if len(result.keys()) >= max_classes:
                    error = _('More than <b>{0}</b> classes found in the class '
                            'attribute <b>"{1}"</b>. Please select another class '
                            'attribute.').format(max_classes, attributes[clsCol][0])
                    break
                else:
                    result[cls] = []
            result[cls].append([cells[x], cells[y]])
        else:
            # analyse file header
            row_std = row.strip().lower()
            if row_std.startswith("@data"):
                data_sec = True

                if clsCol is None:
                    if arff_cls is not None:
                        # use arff class attribute, if defined
                        clsCol = arff_cls
                    else:
                        # otherwise, use last column
                        if len(attributes) > 0:
                            clsCol = len(attributes) - 1
                if clsCol is not None:
                    clsType = attributes[clsCol][1]

                if x is None or y is None or clsCol is None:
                    error = _("Please specify columns for rendering, as default choices could not be used.")
                    break
            elif row_std.startswith("@attribute"):
                parts = row.split()
                col_name = parts[1]
                col_type = parts[2]
                attr_no = re.findall("^attr(\d+)$", col_name)
                if attr_no:
                    attributes.append([_("attr{0}").format(attr_no[0]), col_type])
                else:
                    attributes.append([col_name, col_type])
                attr_idx = len(attributes) - 1
                if x is None and col_type != "string":
                    x = attr_idx
                elif y is None and col_type != "string":
                    y = attr_idx
                if col_name == "class":
                    # save the number of the class column
                    arff_cls = attr_idx
    f.close()

    if not error and clsType != "string" and clsType != "integer":
        # second read
        f = open(BUILDOUT_DIR + '/var/www' + file_url)
        f = strip_arff_header(f)

        step = 1. * (maxCls - minCls) / max_classes
        groups = [str(t) + " - " + str(t + step) for t in arange(minCls, maxCls, step)]
        for row in f:
            cells = row.rstrip().split(",")
            val = float(cells[clsCol])
            group_no = int(floor((1.0 * (val - minCls) * max_classes) / (maxCls - minCls)))
            if group_no == len(groups):
                group_no -= 1
            cls = groups[group_no]
            if not cls in result:
                result[cls] = []
            result[cls].append([cells[x], cells[y]])
        f.close()

    try:
        result = OrderedDict(sorted(result.items(), key=lambda x: float(unicode(x[0]).split(" - ")[0])))
    except ValueError:
        result = OrderedDict(sorted(result.items(), key=lambda x: slugify(unicode(x[0]))))
    result = [{"group": cls, "data": data} for cls, data in result.items()]
    return error, attributes, {"data": result, "minX": minX, "maxX": maxX, "minY": minY, "maxY": maxY, "minCls": minCls, "maxCls": maxCls}, x, y, clsCol

def download_image(image, file_format):
    '''Prepares the HTTP response to download an image in a given format.

    image - image, as returned by the HTML5 canvas.toDataUrl() function
    file_format - image download format
    '''
    imgstr = re.findall(r'base64,(.*)', image)[0]

    response = HttpResponse(mimetype=FILE_TYPE__TO__MIME_TYPE[file_format])
    response['Content-Disposition'] = 'attachment; filename=%s.%s' % (ugettext("image"), file_format)
    data = imgstr.decode("base64")

    im = Image.open(BytesIO(data)).convert("RGBA")
    image = Image.new('RGBA', im.size, (255, 255, 255, 255))
    image.paste(im, (0, 0), im)

    output = cStringIO.StringIO()
    image.save(output, file_format.upper())

    response.write(output.getvalue())
    return response

@csrf_exempt
@login_required(login_url=reverse_lazy('login'))
def chart_form_view(request):
    '''Handles Ajax (GET or POST) request to update the chart component.

    request - Ajax request. 
        GET fields:
            dataset_url - url of the data file, which is to be rendered ty the chart component
            x - attribute to render in x axis
            y - attribute to render in y axis
            cls - class attribute

        POST fields:
            format - image file format
            image - image data, as returned by HTML5 canvas.toDataUrl() function
    '''
    if request.method == 'POST':
        return download_image(request.POST.get("image"), request.POST.get("format"))

    dataset_url = request.GET.get('dataset_url');

    if (dataset_url):
        x = int(request.GET.get("x")) if not request.GET.get("x") is None else None
        y = int(request.GET.get("y")) if not request.GET.get("y") is None else None
        cls = int(request.GET.get("cls")) if not request.GET.get("cls") is None else None
        error, attributes, content, x, y, cls = read_classified_data(dataset_url, x, y, cls)
        float_cls = attributes[cls][1] == "real"
        context = {"attrs": attributes, "error": error, "x": x, "y": y, "cls": cls, "float_cls": float_cls, "minCls": content["minCls"], "maxCls": content["maxCls"]}
        html = render_to_string("damis/_chart.html", context)
        if error:
            resp = {"status": "ERROR", "html": html}
        else:
            resp = {"status": "SUCCESS", "content": content, "html": html}
        return HttpResponse(json.dumps(resp), content_type="application/json")
    else:
        resp = {"status": "ERROR", "html": unicode(_('You have to execute this experiment first to see the result.'))}
        return HttpResponse(json.dumps(resp), content_type="applicatioin/json")

# User views
def register_view(request):
    form = RegistrationForm()
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            ## Login user
            # username = form.cleaned_data.get('username')
            # password = form.cleaned_data.get('password')
            # user = authenticate(username=username, password=password)
            # if user is not None and user.is_active:
            #     login(request, user)
            #     return HttpResponseRedirect(reverse_lazy('home'))

            receiver = form.cleaned_data.get('email')
            domain = request.get_host()
            subject = _('{0} confirm email').format(domain)
            body = render_to_string('accounts/mail/confirm_email_letter.html', {
                'domain': domain,
                'confirm_email_url': reverse_lazy('confirm-email', kwargs={
                        'uidb36': int_to_base36(user.pk),
                        'token': default_token_generator.make_token(user)
                    }),
            })
            sender = settings.DEFAULT_FROM_EMAIL
            send_mail(subject, body, sender, [receiver])
            return HttpResponseRedirect(reverse_lazy('registration-done'))
    return render(request, 'accounts/register.html', {
        'form': form,
    })

def login_view(request, *args, **kwargs):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data['user']
            if user is not None and user.is_active:
                next_page = request.POST.get('next') or reverse_lazy('home')
                login(request, user)
                return HttpResponseRedirect(next_page)
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {
            'form': form,
            'request': request,
        })

def logout_view(request):
    logout(request)
    request.session.clear()
    return HttpResponseRedirect('/login/')

def profile_settings_view(request):
    form = ProfileForm(instance=request.user)
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            return render(request, 'damis/profile.html', {
                    'form': form,
                    'message': _('Profile updated'),
                })
    return render(request, 'damis/profile.html', {
                'form': form,
            })


@login_required(login_url=reverse_lazy('login'))
def approve_user_view(request, pk):
    user = request.user
    if not user.is_superuser:
        return HttpResponseRedirect(reverse_lazy('login'))
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        raise Http404
    user.activate(domain=request.get_host())
    form = UserUpdateForm(instance=user)
    return render(request, 'damis/user_update.html', {
                'form': form,
                'message': _('User was activated')
            })


def confirm_email_view(request, uidb36, token):
    user = User.objects.get(pk=base36_to_int(uidb36))
    if not user.email_approved and default_token_generator.check_token(user, token):
        user.email_approved = True
        user.save()

        domain = request.get_host()
        subject = _('{0}: Approve {1}').format(domain, user.username)
        body = render_to_string('accounts/mail/approve_registration.html', {
            'domain': domain,
            'user': user,
            'username': user.username,
            'approve_url': reverse_lazy('approve-user', kwargs={'pk': user.pk}),
        })
        sender = settings.DEFAULT_FROM_EMAIL
        receivers = settings.APPROVE_REGISTRATION_EMAILS
        send_mail(subject, body, sender, receivers)

        return HttpResponseRedirect(reverse_lazy('email-confirmed'))
    raise Http404

def reset_password_view(request):
    email_form = EmailForm()
    if request.method == 'POST':
        email_form = EmailForm(request.POST)
        if email_form.is_valid():
            receiver = email_form.cleaned_data.get('email')
            user = User.objects.get(email=receiver)
            domain = request.get_host()
            subject = _('{0} password recovery').format(domain)
            body = render_to_string('accounts/mail/reset_password.html', {
                'domain': domain,
                'user': user.username,
                'recovery_url': reverse_lazy('recover-password', kwargs={
                        'uidb36': int_to_base36(user.pk),
                        'token': default_token_generator.make_token(user)
                    }),
            })
            sender = settings.DEFAULT_FROM_EMAIL
            send_mail(subject, body, sender, [receiver])
            return HttpResponseRedirect(reverse_lazy('recovery-email-sent'))
    else:
        email_form = EmailForm()
    return render(request, 'accounts/reset_password.html', {
                'form': email_form,
            })

def recover_password_view(request, uidb36, token):
    user = User.objects.get(pk=base36_to_int(uidb36))
    if default_token_generator.check_token(user, token):
        if request.method == 'POST':
            form = PasswordRecoveryForm(request.POST)
            if form.is_valid():
                user = form.save(uidb36, token)
                password = form.cleaned_data.get('password')
                user = authenticate(username=user.username, password=password)
                if user is not None and user.is_active:
                    login(request, user)
                return HttpResponseRedirect(reverse_lazy('home'))
        else:
            form = PasswordRecoveryForm()
        return render(request, 'accounts/recover_password.html', {
                'form': form,
            })
    raise Http404
