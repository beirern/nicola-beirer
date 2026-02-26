from django.db import models
from wagtail.models import Page
from wagtail.fields import RichTextField, StreamField
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.blocks import (
    CharBlock,
    ListBlock,
    RichTextBlock,
    StreamBlock,
    StructBlock,
    URLBlock,
)


class ContactLinkBlock(StructBlock):
    label = CharBlock(help_text="e.g. GitHub, LinkedIn, Email")
    url = URLBlock()
    icon_class = CharBlock(required=False, help_text="Optional CSS icon class")

    class Meta:
        template = 'resume/blocks/contact_link.html'
        icon = 'link'


class WorkExperienceBlock(StructBlock):
    company = CharBlock()
    role = CharBlock()
    location = CharBlock(required=False)
    start_date = CharBlock(help_text="e.g. Jan 2020")
    end_date = CharBlock(help_text="e.g. Mar 2023 or Present")
    description = RichTextBlock(required=False)
    achievements = ListBlock(CharBlock(), label="Achievements")

    class Meta:
        template = 'resume/blocks/work_experience.html'
        icon = 'briefcase'


class EducationBlock(StructBlock):
    institution = CharBlock()
    degree = CharBlock()
    location = CharBlock(required=False)
    start_date = CharBlock(help_text="e.g. Sep 2016")
    end_date = CharBlock(help_text="e.g. Jun 2020 or Present")
    notes = CharBlock(required=False)

    class Meta:
        template = 'resume/blocks/education.html'
        icon = 'graduation-cap'


class SkillGroupBlock(StructBlock):
    group_name = CharBlock(help_text="e.g. Languages, Frameworks")
    skills = ListBlock(CharBlock())

    class Meta:
        template = 'resume/blocks/skill_group.html'
        icon = 'list-ul'


class CertificationBlock(StructBlock):
    name = CharBlock()
    issuer = CharBlock()
    date = CharBlock(help_text="e.g. Nov 2022")
    url = URLBlock(required=False)

    class Meta:
        icon = 'certificate'


class ResumeStreamBlock(StreamBlock):
    work_experience = WorkExperienceBlock(group="Experience")
    education = EducationBlock(group="Education")
    skill_group = SkillGroupBlock(group="Skills")
    certification = CertificationBlock(group="Certifications")


class ResumePage(Page):
    full_name = models.CharField(max_length=255)
    professional_title = models.CharField(max_length=255)
    bio = RichTextField(blank=True)
    contact_links = StreamField(
        [('contact_link', ContactLinkBlock())],
        blank=True,
        use_json_field=True,
    )
    body = StreamField(
        ResumeStreamBlock(),
        blank=True,
        use_json_field=True,
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel('full_name'),
                FieldPanel('professional_title'),
                FieldPanel('bio'),
                FieldPanel('contact_links'),
            ],
            heading="Personal Information",
        ),
        FieldPanel('body'),
    ]

    parent_page_types = ['wagtailcore.Page']
    subpage_types = []

    class Meta:
        verbose_name = "Resume Page"
