"""Praticiens et cabinets fictifs, réutilisés d'un scénario à l'autre."""

from .render import Medecin

VERNET = Medecin(
    nom="Dre méd. Claire Vernet", specialite="médecine interne générale FMH",
    cabinet="Cabinet médical de la Riponne", rue="Rue de la Riponne 12",
    npa="1005", ville="Lausanne", tel="021 546 22 10",
    email="claire.vernet@cabinet-riponne.ch", rcc="H228741", gln="7601000110032")

BRUNNER = Medecin(
    nom="Dr méd. Marc Brunner", specialite="chirurgie orthopédique FMH",
    cabinet="Centre orthopédique de Beaulieu", rue="Avenue des Bergières 24",
    npa="1004", ville="Lausanne", tel="021 641 88 20",
    email="m.brunner@ortho-beaulieu.ch", rcc="H331902", gln="7601000110049")

FAVRE = Medecin(
    nom="Dre méd. Isabelle Favre", specialite="psychiatrie et psychothérapie FMH",
    cabinet="Cabinet des Cèdres", rue="Chemin des Cèdres 8",
    npa="1004", ville="Lausanne", tel="021 312 45 60",
    email="i.favre@cabinet-cedres.ch", rcc="H445118", gln="7601000110056")

MORAND = Medecin(
    nom="Dr méd. Pierre Morand", specialite="médecine générale FMH",
    cabinet="Permanence de Chauderon", rue="Place Chauderon 5",
    npa="1003", ville="Lausanne", tel="021 320 71 10",
    email="p.morand@permanence-chauderon.ch", rcc="H117246", gln="7601000110063")

KELLER = Medecin(
    nom="Dre méd. Anna Keller", specialite="rhumatologie FMH",
    cabinet="Cabinet de rhumatologie du Léman", rue="Rue du Simplon 14",
    npa="1006", ville="Lausanne", tel="021 601 33 44",
    email="a.keller@rhumato-leman.ch", rcc="H552037", gln="7601000110070")

ROSSIER = Medecin(
    nom="Dr méd. Julien Rossier", specialite="gynécologie et obstétrique FMH",
    cabinet="Cabinet de gynécologie Montbenon", rue="Allée Ernest-Ansermet 3",
    npa="1003", ville="Lausanne", tel="021 351 62 80",
    email="j.rossier@gyneco-montbenon.ch", rcc="H663184", gln="7601000110087")

SCHMID = Medecin(
    nom="Dr méd. Thomas Schmid", specialite="médecine du travail",
    cabinet="Service médical régional Nord vaudois", rue="Rue des Moulins 21",
    npa="1400", ville="Yverdon-les-Bains", tel="024 425 19 30",
    email="t.schmid@smr-nordvaudois.ch", rcc="H774295", gln="7601000110094")
