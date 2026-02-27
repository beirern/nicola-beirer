from django.shortcuts import render

from blog.models import BlogPage
from adventures.models import AdventurePage
from projects.models import ResumeProject


def home(request):
    context = {
        'recent_posts': BlogPage.objects.live().order_by('-date')[:3],
        'recent_adventures': AdventurePage.objects.live().order_by('-date_start')[:3],
        'recent_projects': ResumeProject.objects.all()[:3],
    }
    return render(request, 'home.html', context)
