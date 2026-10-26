from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Commentaire, Jaime, Mention, MentionCommentaire, NotificationCommunaute, Publication

User = get_user_model()


class CommunityViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", "motdepasse", first_name="Alice")
        cls.bob = User.objects.create_user("bob", "bob@example.com", "motdepasse", first_name="Bob")
        cls.charlie = User.objects.create_user("charlie", "charlie@example.com", "motdepasse")
        cls.admin = User.objects.create_superuser("admin", "admin@example.com", "motdepasse")
        cls.post = Publication.objects.create(auteur=cls.alice, texte="Une astuce anti-gaspillage")

    def setUp(self):
        self.client.force_login(self.alice)

    def test_fil_exige_connexion_et_affiche_publication(self):
        self.client.logout()
        response = self.client.get(reverse("community:fil"))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("community:fil"))
        self.assertContains(response, "Une astuce anti-gaspillage")

    def test_creer_publication_avec_mention(self):
        response = self.client.post(reverse("community:publier"), {
            "texte": "Bravo pour cette recette", "mentions": [self.bob.pk],
        })
        publication = Publication.objects.exclude(pk=self.post.pk).get()
        self.assertRedirects(response, publication.get_absolute_url())
        self.assertIn("@bob", publication.texte)
        self.assertTrue(Mention.objects.filter(publication=publication, utilisateur=self.bob).exists())
        self.assertTrue(NotificationCommunaute.objects.filter(
            publication=publication, destinataire=self.bob,
            type=NotificationCommunaute.Type.PUBLICATION,
        ).exists())

    def test_publication_vide_est_refusee(self):
        response = self.client.post(reverse("community:publier"), {"texte": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ajoutez un texte ou une image")

    def test_recherche_utilisateur_exclut_le_compte_connecte(self):
        response = self.client.get(reverse("community:rechercher_utilisateurs"), {"q": "ali"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resultats"], [])
        response = self.client.get(reverse("community:rechercher_utilisateurs"), {"q": "bo"})
        self.assertEqual(response.json()["resultats"][0]["username"], "bob")

    def test_like_est_un_basculeur(self):
        url = reverse("community:aimer", args=[self.post.pk])
        self.client.post(url)
        self.assertTrue(Jaime.objects.filter(publication=self.post, utilisateur=self.alice).exists())
        self.client.post(url)
        self.assertFalse(Jaime.objects.filter(publication=self.post, utilisateur=self.alice).exists())

    def test_commenter_et_supprimer_son_commentaire(self):
        self.client.post(reverse("community:commenter", args=[self.post.pk]), {"contenu": "Très utile !"})
        commentaire = Commentaire.objects.get()
        self.assertEqual(commentaire.auteur, self.alice)
        self.client.post(reverse("community:supprimer_commentaire", args=[commentaire.pk]))
        self.assertFalse(Commentaire.objects.exists())

    def test_mention_dans_commentaire_cree_notification(self):
        response = self.client.post(
            reverse("community:commenter", args=[self.post.pk]),
            {"contenu": "Merci @bob pour cette idée"},
        )
        self.assertEqual(response.status_code, 302)
        commentaire = Commentaire.objects.get()
        self.assertTrue(MentionCommentaire.objects.filter(
            commentaire=commentaire, utilisateur=self.bob
        ).exists())
        self.assertTrue(NotificationCommunaute.objects.filter(
            commentaire=commentaire, destinataire=self.bob,
            type=NotificationCommunaute.Type.COMMENTAIRE,
        ).exists())

    def test_notification_est_marquee_lue_en_l_ouvrant(self):
        notification = NotificationCommunaute.objects.create(
            destinataire=self.alice, acteur=self.bob,
            type=NotificationCommunaute.Type.PUBLICATION, publication=self.post,
        )
        response = self.client.post(reverse("community:lire_notification", args=[notification.pk]))
        notification.refresh_from_db()
        self.assertRedirects(response, self.post.get_absolute_url())
        self.assertIsNotNone(notification.lue_le)

    def test_administration_communaute_est_reservee_et_permet_masquage(self):
        url = reverse("community:administration")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(reverse("community:moderer_publication", args=[self.post.pk]))
        self.post.refresh_from_db()
        self.assertTrue(self.post.est_masquee)

    def test_un_membre_ne_supprime_pas_le_contenu_d_un_autre(self):
        self.client.force_login(self.bob)
        response = self.client.post(reverse("community:supprimer", args=[self.post.pk]))
        self.assertEqual(response.status_code, 403)
        commentaire = Commentaire.objects.create(publication=self.post, auteur=self.alice, contenu="Test")
        response = self.client.post(reverse("community:supprimer_commentaire", args=[commentaire.pk]))
        self.assertEqual(response.status_code, 403)

    def test_repartage_est_unique_par_membre(self):
        self.client.force_login(self.bob)
        url = reverse("community:partager", args=[self.post.pk])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(Publication.objects.filter(auteur=self.bob, publication_originale=self.post).count(), 1)

    def test_publications_masquees_absentes_du_fil(self):
        Publication.objects.create(auteur=self.bob, texte="Contenu masqué", est_masquee=True)
        response = self.client.get(reverse("community:fil"))
        self.assertNotContains(response, "Contenu masqué")

    def test_profil_membre_affiche_uniquement_ses_publications(self):
        Publication.objects.create(auteur=self.bob, texte="Publication Bob")
        response = self.client.get(reverse("community:profil_membre", args=["bob"]))
        self.assertContains(response, "Publication Bob")
        self.assertNotContains(response, "Une astuce anti-gaspillage")
