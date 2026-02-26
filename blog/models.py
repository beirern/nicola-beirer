import datetime

from django.db import models
from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey
from taggit.models import TaggedItemBase
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.blocks import CharBlock, ChoiceBlock, RichTextBlock, StructBlock, TextBlock
from wagtail.embeds.blocks import EmbedBlock
from wagtail.fields import RichTextField, StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.models import Page


class BlogPageTag(TaggedItemBase):
    content_object = ParentalKey(
        'blog.BlogPage',
        related_name='tagged_items',
        on_delete=models.CASCADE,
    )


class HeadingBlock(StructBlock):
    text = CharBlock()
    level = ChoiceBlock(choices=[
        ('h2', 'H2'),
        ('h3', 'H3'),
        ('h4', 'H4'),
    ])

    class Meta:
        template = 'blog/blocks/heading_block.html'
        icon = 'title'


class ImageBlock(StructBlock):
    image = ImageChooserBlock()
    caption = CharBlock(required=False)

    class Meta:
        template = 'blog/blocks/image_block.html'
        icon = 'image'


class CodeBlock(StructBlock):
    language = ChoiceBlock(choices=[
        ('python', 'Python'),
        ('javascript', 'JavaScript'),
        ('typescript', 'TypeScript'),
        ('bash', 'Bash'),
        ('html', 'HTML'),
        ('css', 'CSS'),
        ('json', 'JSON'),
        ('sql', 'SQL'),
    ])
    code = TextBlock()

    class Meta:
        template = 'blog/blocks/code_block.html'
        icon = 'code'


class BlogIndexPage(Page):
    intro = RichTextField(blank=True)

    content_panels = Page.content_panels + [FieldPanel('intro')]
    parent_page_types = ['wagtailcore.Page']
    subpage_types = ['blog.BlogPage']

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['blog_posts'] = BlogPage.objects.child_of(self).live().order_by('-date')
        return context

    class Meta:
        verbose_name = 'Blog Index Page'


class BlogPage(Page):
    date = models.DateField(default=datetime.date.today)
    intro = models.CharField(max_length=500, blank=True)
    header_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    body = StreamField([
        ('heading', HeadingBlock()),
        ('paragraph', RichTextBlock(
            features=['bold', 'italic', 'link', 'ol', 'ul', 'blockquote'],
            template='blog/blocks/paragraph_block.html',
        )),
        ('image', ImageBlock()),
        ('video', EmbedBlock(
            help_text='Paste a YouTube or Vimeo URL',
            template='blog/blocks/video_block.html',
            icon='media',
            label='Video Embed',
        )),
        ('code', CodeBlock()),
    ], blank=True, use_json_field=True)
    tags = ClusterTaggableManager(through=BlogPageTag, blank=True)

    content_panels = Page.content_panels + [
        MultiFieldPanel([FieldPanel('date'), FieldPanel('tags')], heading='Post Metadata'),
        FieldPanel('intro'),
        FieldPanel('header_image'),
        FieldPanel('body'),
    ]

    parent_page_types = ['blog.BlogIndexPage']
    subpage_types = []

    class Meta:
        verbose_name = 'Blog Post'
        ordering = ['-date']
