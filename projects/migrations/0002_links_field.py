from django.db import migrations, models


def migrate_links_forward(apps, schema_editor):
    ResumeProject = apps.get_model('projects', 'ResumeProject')
    old_fields = [
        ('live_url', 'live'),
        ('github_url', 'github'),
        ('blog_post_url', 'blog post'),
    ]
    for project in ResumeProject.objects.all():
        links = []
        for field, label in old_fields:
            url = getattr(project, field, '')
            if url:
                links.append({'label': label, 'url': url})
        project.links = links
        project.save()


def migrate_links_backward(apps, schema_editor):
    ResumeProject = apps.get_model('projects', 'ResumeProject')
    label_to_field = {'live': 'live_url', 'github': 'github_url', 'blog post': 'blog_post_url'}
    for project in ResumeProject.objects.all():
        for link in project.links:
            field = label_to_field.get(link.get('label'))
            if field:
                setattr(project, field, link['url'])
        project.save()


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='resumeproject',
            name='links',
            field=models.JSONField(default=list, help_text='List of {"label": "...", "url": "..."} objects'),
        ),
        migrations.RunPython(migrate_links_forward, migrate_links_backward),
        migrations.RemoveField(model_name='resumeproject', name='live_url'),
        migrations.RemoveField(model_name='resumeproject', name='github_url'),
        migrations.RemoveField(model_name='resumeproject', name='blog_post_url'),
    ]
