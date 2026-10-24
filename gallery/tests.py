from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from wagtail.models import Page, Site

from adventures.models import AdventureIndexPage, AdventurePage
from gallery.models import GalleryAlbumPage, GalleryIndexPage


class GalleryAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        root = Page.objects.get(depth=1)
        Site.objects.update(root_page=root)
        gallery = root.add_child(instance=GalleryIndexPage(title='Gallery', slug='gallery'))
        gallery.save_revision().publish()
        album = gallery.add_child(
            instance=GalleryAlbumPage(
                title='Private album', slug='private-album', date=date(2026, 1, 1)
            )
        )
        album.save_revision().publish()
        adventures = root.add_child(
            instance=AdventureIndexPage(title='Adventures', slug='adventures')
        )
        adventures.save_revision().publish()
        adventure = adventures.add_child(
            instance=AdventurePage(title='Test trip', slug='test-trip')
        )
        adventure.save_revision().publish()
        album.adventure_page = adventure
        album.save()

        User = get_user_model()
        cls.reader = User.objects.create_user('reader', password='password')
        cls.admin = User.objects.create_superuser(
            'admin', 'admin@example.com', 'password'
        )

    def test_public_and_regular_user_cannot_see_gallery(self):
        for user in (None, self.reader):
            with self.subTest(user=user):
                if user:
                    self.client.force_login(user)
                else:
                    self.client.logout()
                self.assertNotContains(self.client.get('/'), 'href="/gallery/"')
                self.assertEqual(self.client.get('/gallery/').status_code, 404)
                self.assertEqual(
                    self.client.get('/gallery/private-album/').status_code, 404
                )
                self.assertNotContains(
                    self.client.get('/adventures/test-trip/'), 'Private album'
                )

    def test_admin_can_see_gallery_and_adventure_link(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/'), 'href="/gallery/"')
        self.assertContains(self.client.get('/gallery/'), 'Private album')
        self.assertContains(self.client.get('/gallery/private-album/'), 'Private album')
        self.assertContains(
            self.client.get('/adventures/test-trip/'), 'Private album'
        )
