from django.shortcuts import render

from .models import ResumeProject


def index(request):
    projects = ResumeProject.objects.all()
    return render(request, 'projects/index.html', {'projects': projects})
