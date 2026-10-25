import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from nicolabeirer.renditions import ALL_SPECS

IMAGE_TAG = re.compile(r'{%\s*image\s+\S+\s+([\w-]+)')


class RenditionSpecTests(SimpleTestCase):
    def test_every_template_size_is_prebuilt(self):
        used = set()
        for template in Path(settings.BASE_DIR).rglob('*.html'):
            if '.venv' in template.parts or 'node_modules' in template.parts:
                continue
            used.update(IMAGE_TAG.findall(template.read_text()))
        self.assertTrue(used)
        self.assertEqual(used - ALL_SPECS, set(), 'add these sizes to nicolabeirer/renditions.py')
