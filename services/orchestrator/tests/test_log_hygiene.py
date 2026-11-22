"""
Journaux sans données patient (#32, audit S8).

Une réponse du modèle reprend le dossier : nom, date de naissance,
diagnostics. Une erreur d'analyse qui la recopie finit dans les journaux du
conteneur, conservés sans limite de durée. Ces tests font échouer la synthèse
de toutes les façons prévues et vérifient qu'aucun fragment du dossier ni nom
de fichier n'apparaît dans les journaux. Données fictives uniquement.
"""

import asyncio
import logging

import httpx
import pytest

import medical_synthesis
from tests import fakes

PATIENT = "Patient Test"
SECRET_TEXT = PATIENT + ", né le 01.01.1970, diagnostic fictif Z99.9"
FILENAME = "Rapport_Patient_Test_1970.pdf"
DOCS = [dict(filename=FILENAME, markdown="# Rapport\n\n" + SECRET_TEXT)]


def _run():
    return asyncio.run(medical_synthesis.run_medical_synthesis(DOCS, "http://vllm.invalid/v1", "model"))


def _assert_clean(caplog) -> None:
    logged = caplog.text
    assert PATIENT not in logged
    assert "01.01.1970" not in logged
    assert FILENAME not in logged
    assert "Patient_Test" not in logged


def test_parse_error_carries_the_length_not_the_text():
    with pytest.raises(ValueError) as exc:
        medical_synthesis._extract_json_from_response("Voici le dossier de " + SECRET_TEXT)
    message = str(exc.value)
    assert PATIENT not in message
    assert "caractères" in message


def test_non_json_answer_leaves_no_patient_data_in_logs(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    fakes.install(monkeypatch, lambda request: fakes.completion("Voici le dossier de " + SECRET_TEXT))
    assert _run() is None
    assert caplog.records, "la synthèse en échec doit laisser une trace"
    _assert_clean(caplog)


def test_refused_request_leaves_no_patient_data_in_logs(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    # Un serveur qui recopie le prompt dans son message d'erreur.
    fakes.install(monkeypatch, lambda request: httpx.Response(400, text="prompt refusé : " + SECRET_TEXT))
    assert _run() is None
    _assert_clean(caplog)
